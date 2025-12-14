import asyncio
from typing import Callable, Optional
import discord


class DiscordListener:
    """
    Discord user client that listens for trading alerts.

    Uses your personal Discord account token to monitor channels.
    Monitors specific channels and captures messages from configured traders.
    Forwards messages to a callback for processing.

    NOTE: This uses a user token, not a bot token.
    """

    def __init__(
        self,
        token: str,
        channel_ids: list[int],
        monitored_users: Optional[list[str]] = None,
        message_callback: Optional[Callable] = None,
    ):
        """
        Initialize Discord listener.

        Args:
            token: Discord user account token
            channel_ids: List of channel IDs to monitor
            monitored_users: List of Discord usernames to monitor (None = all)
            message_callback: Async callback function for each message
                             Signature: async def callback(message, author, message_id, timestamp)
        """
        self.token = token
        self.channel_ids = set(channel_ids)
        self.monitored_users = set(monitored_users) if monitored_users else None
        self.message_callback = message_callback

        # Create user client with all intents for user account
        intents = discord.Intents.all()
        self.client = discord.Client(intents=intents)

        # Register event handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register Discord event handlers."""

        @self.client.event
        async def on_ready():
            print(f"Discord client logged in as {self.client.user}")
            print(f"Monitoring {len(self.channel_ids)} channel(s)")
            if self.monitored_users:
                print(f"Monitoring users: {self.monitored_users}")
            else:
                print("Monitoring all users")

        @self.client.event
        async def on_message(message: discord.Message):
            # Ignore own messages
            if message.author == self.client.user:
                return

            # Check if message is in monitored channel
            if message.channel.id not in self.channel_ids:
                return

            # Check if author is in monitored users (if filter is set)
            if self.monitored_users:
                # Check both username and display name
                author_name = message.author.name
                author_display = message.author.display_name
                author_global = message.author.global_name if hasattr(message.author, 'global_name') else None

                if not any(
                    name in self.monitored_users
                    for name in [author_name, author_display, author_global]
                    if name
                ):
                    return

            # Process message
            await self._process_message(message)

    async def _process_message(self, message: discord.Message):
        """Process a message from Discord."""
        print(
            f"[{message.created_at}] {message.author.name}: {message.content}"
        )

        # Call callback if provided
        if self.message_callback:
            try:
                await self.message_callback(
                    message=message.content,
                    author=message.author.name,
                    message_id=str(message.id),
                    timestamp=message.created_at,
                )
            except Exception as e:
                print(f"Error in message callback: {e}")

    async def start(self):
        """Start the Discord client."""
        try:
            await self.client.start(self.token)
        except Exception as e:
            print(f"Discord client error: {e}")
            raise

    async def stop(self):
        """Stop the Discord client."""
        await self.client.close()

    def run(self):
        """Run the client (blocking)."""
        self.client.run(self.token)


class DiscordListenerSync:
    """
    Synchronous wrapper for DiscordListener.

    Useful for testing or simple integrations.
    """

    def __init__(self, *args, **kwargs):
        self.listener = DiscordListener(*args, **kwargs)
        self.loop = asyncio.new_event_loop()

    def start(self):
        """Start the listener in a new event loop."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.listener.start())

    def stop(self):
        """Stop the listener."""
        self.loop.run_until_complete(self.listener.stop())
        self.loop.close()
