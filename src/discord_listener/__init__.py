from .listener_websocket import DiscordWebSocketListener

# Use WebSocket listener (more reliable for user tokens)
DiscordListener = DiscordWebSocketListener

__all__ = ["DiscordListener"]
