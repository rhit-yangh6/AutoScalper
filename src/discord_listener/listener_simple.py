"""
Simple Discord listener using JSON encoding (based on working DiscordTelegramRouter).

This uses plain JSON instead of zlib compression for better reliability.
"""

import asyncio
import json
import aiohttp
from datetime import datetime, timezone
from typing import Callable, List, Optional


class DiscordSimpleListener:
    """
    Discord listener using JSON encoding (no compression).

    Based on proven working code from DiscordTelegramRouter.
    """

    def __init__(
        self,
        token: str,
        channel_ids: List[int],
        monitored_users: Optional[List[str]] = None,
        message_callback: Optional[Callable] = None,
    ):
        self.token = token
        self.channel_ids = set(channel_ids)
        self.monitored_users = set(monitored_users) if monitored_users else None
        self.message_callback = message_callback

        # Gateway state
        self.session_id = None
        self.sequence = None
        self.heartbeat_interval = None
        self.ws = None
        self.http_session = None
        self.heartbeat_task = None
        self.running = False

        # User info
        self.user_id = None
        self.user_name = None

    async def get_user_info(self) -> bool:
        """Verify Discord token and get user info."""
        headers = {"authorization": self.token}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://discord.com/api/v10/users/@me",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.user_id = data.get('id')
                        self.user_name = data.get('username')
                        print(f"Discord logged in as {self.user_name}")
                        return True
                    else:
                        print(f"Discord authentication failed: HTTP {resp.status}")
                        return False
        except Exception as e:
            print(f"Error getting Discord user info: {e}")
            return False

    async def start(self):
        """Connect to Discord gateway with auto-reconnect."""
        self.running = True

        # Verify token first
        if not await self.get_user_info():
            print("Failed to authenticate with Discord. Check your token.")
            return

        print(f"Monitoring {len(self.channel_ids)} Discord channel(s)")
        if self.monitored_users:
            print(f"Monitoring users: {list(self.monitored_users)}")
        else:
            print("Monitoring all users")

        reconnect_attempts = 0
        max_reconnect_attempts = 10

        while self.running:
            try:
                gateway_url = "wss://gateway.discord.gg"
                print(f"Connecting to Discord gateway...")

                # Create session
                connector = aiohttp.TCPConnector()
                session = aiohttp.ClientSession(connector=connector)
                self.http_session = session

                try:
                    # Connect with JSON encoding (no compression!)
                    async with session.ws_connect(
                        f"{gateway_url}?v=10&encoding=json",
                        autoping=False,
                        max_msg_size=0  # No size limit
                    ) as ws:
                        self.ws = ws
                        print("Connected to Discord gateway")
                        reconnect_attempts = 0  # Reset on successful connection

                        # Send IDENTIFY
                        await self._identify()

                        # Listen for messages
                        async for msg in ws:
                            try:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    data = json.loads(msg.data)
                                    await self._handle_gateway_event(data)
                                elif msg.type == aiohttp.WSMsgType.ERROR:
                                    print(f"WebSocket error: {msg}")
                                    break
                                elif msg.type == aiohttp.WSMsgType.CLOSED:
                                    print("WebSocket closed")
                                    break
                            except json.JSONDecodeError as e:
                                print(f"Failed to decode JSON: {e}")
                                continue
                            except Exception as e:
                                print(f"Error processing message: {e}")
                                continue

                finally:
                    # Cancel heartbeat task
                    if self.heartbeat_task and not self.heartbeat_task.done():
                        self.heartbeat_task.cancel()
                        try:
                            await self.heartbeat_task
                        except asyncio.CancelledError:
                            pass

                    await session.close()

                    if self.running:
                        print("Reconnecting in 5 seconds...")
                        await asyncio.sleep(5)

            except Exception as e:
                reconnect_attempts += 1
                wait_time = min(5 * reconnect_attempts, 60)

                if self.running and reconnect_attempts <= max_reconnect_attempts:
                    print(f"Connection error (attempt {reconnect_attempts}/{max_reconnect_attempts}): {e}")
                    print(f"Reconnecting in {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                else:
                    if self.running:
                        print(f"Failed to reconnect after {max_reconnect_attempts} attempts")
                    break

    async def stop(self):
        """Stop the Discord listener."""
        self.running = False
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self.http_session:
            await self.http_session.close()

    async def _identify(self):
        """Send IDENTIFY payload to authenticate."""
        payload = {
            "op": 2,  # IDENTIFY
            "d": {
                "token": self.token,
                "intents": 32768 + 512,  # GUILD_MESSAGES + MESSAGE_CONTENT
                "properties": {
                    "os": "Linux",
                    "browser": "AutoScalper",
                    "device": "AutoScalper"
                }
            }
        }
        await self.ws.send_json(payload)

    async def _handle_gateway_event(self, data: dict):
        """Handle incoming gateway events."""
        op = data.get('op')
        event_type = data.get('t')
        event_data = data.get('d', {})

        # HEARTBEAT request
        if op == 1:
            await self._send_heartbeat()

        # HELLO (start heartbeat)
        elif op == 10:
            self.heartbeat_interval = event_data.get('heartbeat_interval')
            print(f"Heartbeat interval: {self.heartbeat_interval}ms")

            # Cancel old heartbeat task
            if self.heartbeat_task and not self.heartbeat_task.done():
                self.heartbeat_task.cancel()
                try:
                    await self.heartbeat_task
                except asyncio.CancelledError:
                    pass

            # Start new heartbeat
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # DISPATCH events
        elif op == 0:
            self.sequence = data.get('s', self.sequence)

            if event_type == 'READY':
                self.session_id = event_data.get('session_id')
                print(f"Discord READY - session: {self.session_id}")

            elif event_type == 'MESSAGE_CREATE':
                await self._handle_message(event_data)

            elif event_type == 'MESSAGE_UPDATE':
                # Also handle edited messages
                await self._handle_message(event_data)

    async def _handle_message(self, message: dict):
        """Handle MESSAGE_CREATE and MESSAGE_UPDATE events."""
        try:
            channel_id = int(message.get('channel_id', 0))

            # Check if in monitored channels
            if channel_id not in self.channel_ids:
                return

            # Get message details
            author = message.get('author', {})
            author_name = author.get('username', 'Unknown')
            content = message.get('content', '').strip()
            message_id = message.get('id', '')
            timestamp_str = message.get('timestamp', '')

            # Skip bot messages
            if author.get('bot', False):
                return

            # Check if monitored user
            if self.monitored_users:
                if author_name not in self.monitored_users:
                    return

            # Skip empty content
            if not content:
                print(f"[DEBUG] Empty message from {author_name} - skipping")
                return

            # Parse timestamp
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except:
                timestamp = datetime.now(timezone.utc)

            # Log message
            print(f"[{timestamp.strftime('%H:%M:%S')}] {author_name}: {content}")

            # Call callback
            if self.message_callback:
                try:
                    await self.message_callback(
                        message=content,
                        author=author_name,
                        message_id=message_id,
                        timestamp=timestamp,
                    )
                except Exception as e:
                    print(f"Error in message callback: {e}")

        except Exception as e:
            print(f"Error handling Discord message: {e}")

    async def _send_heartbeat(self):
        """Send heartbeat to keep connection alive."""
        if not self.ws or self.ws.closed:
            raise ConnectionError("WebSocket is closed")

        payload = {
            "op": 1,  # HEARTBEAT
            "d": self.sequence
        }
        await self.ws.send_json(payload)

    async def _heartbeat_loop(self):
        """Send periodic heartbeats."""
        try:
            while True:
                if self.heartbeat_interval:
                    await asyncio.sleep(self.heartbeat_interval / 1000)
                    try:
                        await self._send_heartbeat()
                    except (ConnectionError, ConnectionResetError, OSError) as e:
                        print(f"Heartbeat stopped: {e}")
                        break
        except asyncio.CancelledError:
            pass  # Normal cancellation
        except Exception as e:
            print(f"Heartbeat error: {e}")
