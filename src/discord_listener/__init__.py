from .listener_simple import DiscordSimpleListener
from .listener_websocket import DiscordWebSocketListener

# Use Simple listener (JSON encoding - proven working from DiscordTelegramRouter)
DiscordListener = DiscordSimpleListener

# Old zlib-based listener available as fallback
# DiscordListener = DiscordWebSocketListener

__all__ = ["DiscordListener", "DiscordSimpleListener", "DiscordWebSocketListener"]
