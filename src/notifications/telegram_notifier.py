"""
Telegram notification system for trading alerts.

Sends notifications via Telegram Bot API for:
- Order submissions
- Order fills
- End-of-day summaries
"""

import asyncio
import aiohttp
from datetime import datetime, date
from typing import Optional, List, Dict
from enum import Enum

from ..models import TradeSession, EventType, Direction
from ..execution.executor import OrderResult, OrderStatus


class NotificationType(str, Enum):
    """Types of notifications."""
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    DAILY_SUMMARY = "DAILY_SUMMARY"
    ERROR = "ERROR"


class TelegramNotifier:
    """
    Sends trading notifications to Telegram.

    Uses Telegram Bot API via HTTP POST.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        enabled: bool = True,
    ):
        """
        Initialize Telegram notifier.

        Args:
            bot_token: Telegram bot token from @BotFather
            chat_id: Your Telegram chat ID (get from @userinfobot)
            enabled: Enable/disable notifications
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled
        self.api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        # Track daily stats
        self.daily_orders: List[Dict] = []
        self.daily_fills: List[Dict] = []

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Send a message to Telegram.

        Args:
            text: Message text (supports HTML formatting)
            parse_mode: "HTML" or "Markdown"

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.enabled:
            return False

        if not self.bot_token or not self.chat_id:
            print("⚠️  Telegram not configured (missing bot_token or chat_id)")
            return False

        try:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload, timeout=10) as response:
                    if response.status == 200:
                        return True
                    else:
                        error_text = await response.text()
                        print(f"⚠️  Telegram API error: {response.status} - {error_text}")
                        return False

        except asyncio.TimeoutError:
            print("⚠️  Telegram notification timed out")
            return False
        except Exception as e:
            print(f"⚠️  Failed to send Telegram notification: {e}")
            return False

    async def notify_order_submitted(
        self,
        session: TradeSession,
        event_type: EventType,
        order_details: dict,
        paper_mode: bool = True,
    ):
        """
        Notify when an order is submitted to IBKR.

        Args:
            session: Trading session
            event_type: Type of event (NEW, ADD, EXIT, etc.)
            order_details: Order details dict
            paper_mode: Whether in paper trading mode
        """
        # Track for daily summary
        self.daily_orders.append({
            'time': datetime.utcnow(),
            'session_id': session.session_id,
            'event_type': event_type.value,
            'details': order_details,
        })

        # Format message
        mode = "📝 PAPER" if paper_mode else "🔴 LIVE"
        symbol = f"{session.underlying} {session.strike}{session.direction.value[0]}" if session.direction else "UNKNOWN"

        text = f"<b>{mode} ORDER SUBMITTED</b>\n\n"
        text += f"<b>Action:</b> {event_type.value}\n"
        text += f"<b>Symbol:</b> {symbol}\n"
        text += f"<b>Expiry:</b> {session.expiry}\n"

        if order_details.get('quantity'):
            text += f"<b>Quantity:</b> {order_details['quantity']} contracts\n"

        if order_details.get('entry_price'):
            text += f"<b>Entry:</b> ${order_details['entry_price']:.2f}\n"

        if order_details.get('stop_loss'):
            text += f"<b>Stop:</b> ${order_details['stop_loss']:.2f}\n"

        if order_details.get('targets'):
            targets_str = ", ".join([f"${t:.2f}" for t in order_details['targets']])
            text += f"<b>Targets:</b> {targets_str}\n"

        text += f"\n<i>Session: {session.session_id[:8]}...</i>"
        text += f"\n<i>Time: {datetime.utcnow().strftime('%H:%M:%S UTC')}</i>"

        await self.send_message(text)

    async def notify_order_filled(
        self,
        session: TradeSession,
        event_type: EventType,
        result: OrderResult,
        paper_mode: bool = True,
    ):
        """
        Notify when an order is filled (or rejected/cancelled).

        Args:
            session: Trading session
            event_type: Type of event
            result: Order result
            paper_mode: Whether in paper trading mode
        """
        # Track for daily summary
        self.daily_fills.append({
            'time': datetime.utcnow(),
            'session_id': session.session_id,
            'event_type': event_type.value,
            'result': {
                'status': result.status,  # Already a string value
                'filled_price': result.filled_price,
                'order_id': result.order_id,
            }
        })

        # result.status is already a string value (Pydantic's use_enum_values = True)
        # Determine emoji and color based on status string
        if result.status == "FILLED":
            emoji = "✅"
            status_text = "FILLED"
        elif result.status == "REJECTED":
            emoji = "❌"
            status_text = "REJECTED"
        elif result.status == "CANCELLED":
            emoji = "⚠️"
            status_text = "CANCELLED"
        else:
            emoji = "ℹ️"
            status_text = result.status

        mode = "📝 PAPER" if paper_mode else "🔴 LIVE"
        symbol = f"{session.underlying} {session.strike}{session.direction.value[0]}" if session.direction else "UNKNOWN"

        text = f"<b>{emoji} {mode} ORDER {status_text}</b>\n\n"
        text += f"<b>Action:</b> {event_type.value}\n"
        text += f"<b>Symbol:</b> {symbol}\n"

        if result.order_id:
            text += f"<b>Order ID:</b> {result.order_id}\n"

        if result.filled_price:
            text += f"<b>Fill Price:</b> ${result.filled_price:.2f}\n"

        if result.message:
            text += f"\n<i>{result.message}</i>\n"

        text += f"\n<i>Session: {session.session_id[:8]}...</i>"
        text += f"\n<i>Time: {datetime.utcnow().strftime('%H:%M:%S UTC')}</i>"

        await self.send_message(text)

    async def send_daily_summary(self, sessions: List[TradeSession], account_balance: Optional[float] = None):
        """
        Send end-of-day summary of all trades.

        Args:
            sessions: List of all sessions for the day
            account_balance: Current account balance from IBKR (optional)
        """
        today = date.today().strftime('%Y-%m-%d')

        # Calculate stats
        total_sessions = len(sessions)
        closed_sessions = [s for s in sessions if s.state == "CLOSED"]
        open_sessions = [s for s in sessions if s.state == "OPEN"]

        total_fills = len(self.daily_fills)
        total_orders = len(self.daily_orders)

        # Calculate P&L (simplified - would need actual fill prices from session)
        total_pnl = 0.0
        winning_trades = 0
        losing_trades = 0

        for session in closed_sessions:
            # This is a placeholder - you'd calculate actual P&L from fills
            # For now, we'll skip P&L calculation
            pass

        # Build message
        text = f"<b>📊 DAILY TRADING SUMMARY</b>\n"
        text += f"<b>Date:</b> {today}\n"

        # Add account balance if available
        if account_balance is not None:
            text += f"<b>💰 Account Balance:</b> ${account_balance:,.2f}\n"

        text += "\n"

        text += f"<b>📈 Sessions</b>\n"
        text += f"• Total: {total_sessions}\n"
        text += f"• Closed: {len(closed_sessions)}\n"
        text += f"• Open: {len(open_sessions)}\n\n"

        text += f"<b>📋 Activity</b>\n"
        text += f"• Orders Submitted: {total_orders}\n"
        text += f"• Orders Filled: {total_fills}\n\n"

        # List sessions
        if closed_sessions:
            text += f"<b>🔒 Closed Positions</b>\n"
            for session in closed_sessions[:5]:  # Show first 5
                symbol = f"{session.underlying} {session.strike}{session.direction.value[0]}" if session.direction else "?"
                events_count = len(session.events)
                text += f"• {symbol} - {events_count} events\n"

            if len(closed_sessions) > 5:
                text += f"<i>... and {len(closed_sessions) - 5} more</i>\n"
            text += "\n"

        if open_sessions:
            text += f"<b>🔓 Open Positions</b>\n"
            for session in open_sessions:
                symbol = f"{session.underlying} {session.strike}{session.direction.value[0]}" if session.direction else "?"
                qty = session.total_quantity
                text += f"• {symbol} - {qty} contracts\n"
            text += "\n"

        text += f"<i>Summary generated at {datetime.utcnow().strftime('%H:%M:%S UTC')}</i>"

        await self.send_message(text)

        # Reset daily counters
        self.daily_orders = []
        self.daily_fills = []

    async def notify_error(self, error_type: str, error_message: str):
        """
        Send error notification.

        Args:
            error_type: Type of error
            error_message: Error message
        """
        text = f"<b>🚨 ERROR ALERT</b>\n\n"
        text += f"<b>Type:</b> {error_type}\n"
        text += f"<b>Message:</b> {error_message}\n"
        text += f"\n<i>Time: {datetime.utcnow().strftime('%H:%M:%S UTC')}</i>"

        await self.send_message(text)

    def get_daily_stats(self) -> dict:
        """Get current daily statistics."""
        return {
            'total_orders': len(self.daily_orders),
            'total_fills': len(self.daily_fills),
            'orders': self.daily_orders,
            'fills': self.daily_fills,
        }


# Global notifier instance
_notifier: Optional[TelegramNotifier] = None


def get_notifier() -> Optional[TelegramNotifier]:
    """Get the global Telegram notifier instance."""
    return _notifier


def init_notifier(bot_token: str, chat_id: str, enabled: bool = True) -> TelegramNotifier:
    """Initialize the global Telegram notifier."""
    global _notifier
    _notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id, enabled=enabled)
    return _notifier
