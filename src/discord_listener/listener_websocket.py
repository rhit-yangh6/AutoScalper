import asyncio
import json
import zlib
from typing import Callable, Optional
import aiohttp
from datetime import datetime


class DiscordWebSocketListener:
    """
    Discord listener using direct WebSocket connection.

    More reliable for user tokens than discord.py-self.
    Uses Discord Gateway API directly.
    """

    def __init__(
        self,
        token: str,
        channel_ids: list[int],
        monitored_users: Optional[list[str]] = None,
        message_callback: Optional[Callable] = None,
    ):
        self.token = token
        self.channel_ids = set(channel_ids)
        self.monitored_users = set(monitored_users) if monitored_users else None
        self.message_callback = message_callback

        self.ws = None
        self.session = None
        self.heartbeat_interval = None
        self.sequence = None
        self.session_id = None
        self.running = False

        # For zlib decompression
        self.inflator = zlib.decompressobj()

    async def start(self):
        """Start the WebSocket connection with auto-reconnect."""
        self.running = True
        self.session = aiohttp.ClientSession()

        reconnect_delay = 5  # seconds
        max_reconnect_delay = 60

        while self.running:
            try:
                # Connect to Discord Gateway
                gateway_url = "wss://gateway.discord.gg/?v=10&encoding=json&compress=zlib-stream"

                async with self.session.ws_connect(gateway_url) as ws:
                    self.ws = ws
                    print("Connected to Discord Gateway")

                    # Reset reconnect delay on successful connection
                    reconnect_delay = 5

                    # Handle messages
                    await self._handle_messages()

            except Exception as e:
                if self.running:
                    print(f"Discord WebSocket error: {e}")
                    print(f"Reconnecting in {reconnect_delay} seconds...")
                    await asyncio.sleep(reconnect_delay)

                    # Exponential backoff
                    reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)
                else:
                    # Stop requested, don't reconnect
                    break

        # Clean up
        if self.session:
            await self.session.close()

    async def stop(self):
        """Stop the WebSocket connection."""
        self.running = False
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()

    async def _handle_messages(self):
        """Handle incoming WebSocket messages."""
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.BINARY:
                # Decompress message
                payload = self._decompress(msg.data)
                await self._handle_payload(payload)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                print(f"WebSocket error: {msg}")
                break

    def _decompress(self, data: bytes) -> dict:
        """Decompress zlib compressed data."""
        buffer = self.inflator.decompress(data)
        return json.loads(buffer.decode('utf-8'))

    async def _handle_payload(self, payload: dict):
        """Handle a Discord gateway payload."""
        op = payload.get('op')
        d = payload.get('d')
        s = payload.get('s')
        t = payload.get('t')

        # Update sequence
        if s is not None:
            self.sequence = s

        # Handle different opcodes
        if op == 10:  # Hello
            await self._handle_hello(d)
        elif op == 0:  # Dispatch
            await self._handle_dispatch(t, d)
        elif op == 1:  # Heartbeat request
            await self._send_heartbeat()
        elif op == 7:  # Reconnect
            print("Discord requested reconnect")
            # Should reconnect
        elif op == 9:  # Invalid session
            print("Invalid session, reconnecting...")
            await asyncio.sleep(5)
            await self._identify()
        elif op == 11:  # Heartbeat ACK
            pass  # Heartbeat acknowledged

    async def _handle_hello(self, data: dict):
        """Handle HELLO payload."""
        self.heartbeat_interval = data['heartbeat_interval'] / 1000.0

        # Start heartbeat
        asyncio.create_task(self._heartbeat_loop())

        # Identify
        await self._identify()

    async def _identify(self):
        """Send IDENTIFY payload."""
        payload = {
            "op": 2,
            "d": {
                "token": self.token,
                "properties": {
                    "$os": "macos",
                    "$browser": "chrome",
                    "$device": "chrome"
                },
                "intents": 513  # GUILDS + GUILD_MESSAGES
            }
        }
        await self.ws.send_json(payload)

    async def _heartbeat_loop(self):
        """Send periodic heartbeats."""
        while self.running:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await self._send_heartbeat()
            except Exception as e:
                print(f"Heartbeat error: {e}")
                # Connection lost, will be handled by main loop
                break

    async def _send_heartbeat(self):
        """Send heartbeat to keep connection alive."""
        if self.ws and not self.ws.closed:
            try:
                payload = {
                    "op": 1,
                    "d": self.sequence
                }
                await self.ws.send_json(payload)
            except Exception as e:
                print(f"Failed to send heartbeat: {e}")
                raise  # Re-raise to be caught by heartbeat_loop

    async def _handle_dispatch(self, event_type: str, data: dict):
        """Handle dispatch events."""
        if event_type == "READY":
            self.session_id = data.get('session_id')
            user = data.get('user', {})
            username = user.get('username', 'Unknown')
            print(f"Discord client logged in as {username}")
            print(f"Monitoring {len(self.channel_ids)} channel(s)")
            if self.monitored_users:
                print(f"Monitoring users: {self.monitored_users}")
            else:
                print("Monitoring all users")

        elif event_type == "MESSAGE_CREATE":
            await self._handle_message(data)

        elif event_type == "MESSAGE_UPDATE":
            # Handle edited messages
            await self._handle_message(data)

    async def _handle_message(self, data: dict):
        """Handle MESSAGE_CREATE event."""
        # Get message details
        channel_id = int(data.get('channel_id', 0))
        author = data.get('author', {})
        content = data.get('content', '')
        message_id = data.get('id', '')
        timestamp_str = data.get('timestamp', '')

        # Check if in monitored channel
        if channel_id not in self.channel_ids:
            return

        # Get author info
        author_name = author.get('username', 'Unknown')
        author_id = author.get('id', '')

        # Check if bot (ignore bot messages)
        if author.get('bot', False):
            return

        # Check if self (ignore own messages)
        # We could check this but for now just skip

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
            timestamp = datetime.utcnow()

        # Log message
        print(f"[{timestamp}] {author_name}: {content}")

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
