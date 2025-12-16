"""
Telegram notification system for trading alerts.

Sends notifications via Telegram Bot API for:
- Order submissions
- Order fills
- End-of-day summaries
"""

import asyncio
import aiohttp
import json
from datetime import datetime, date, timezone
from pathlib import Path
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

        # Command handling
        self.last_update_id: Optional[int] = None
        self.command_handlers: Dict = {}

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
            'time': datetime.now(timezone.utc),
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
        text += f"\n<i>Time: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}</i>"

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

        # Add P&L for exits
        if event_type in [EventType.SL, EventType.TP, EventType.EXIT]:
            if hasattr(session, 'realized_pnl') and session.realized_pnl is not None:
                pnl = session.realized_pnl
                pnl_emoji = "💰" if pnl > 0 else "📉" if pnl < 0 else "⚪"
                text += f"<b>P&L:</b> {pnl_emoji} ${pnl:+,.2f}\n"

        if result.message:
            text += f"\n<i>{result.message}</i>\n"

        text += f"\n<i>Session: {session.session_id[:8]}...</i>"
        text += f"\n<i>Time: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}</i>"

        await self.send_message(text)

    async def send_daily_summary(
        self,
        date_str: str,
        snapshot: Optional[dict] = None,
        account_balance: Optional[float] = None,
        log_dir: str = "logs"
    ):
        """
        Send end-of-day summary using snapshot + session logs.

        This implementation is resilient to bot restarts - it reads from
        the snapshot file and session JSON logs instead of in-memory state.

        Args:
            date_str: Date to summarize (YYYY-MM-DD format)
            snapshot: Snapshot data (or None to read from file)
            account_balance: Current account balance from IBKR (optional)
            log_dir: Base directory for logs
        """
        # Load snapshot from file if not provided
        if not snapshot:
            from ..logging import DailySnapshotManager
            snapshot_manager = DailySnapshotManager(log_dir)
            snapshot = snapshot_manager.get_snapshot_for_date(date_str)

        starting_balance = snapshot["account_balance"] if snapshot else None

        # Read session logs for the day
        day_dir = Path(log_dir) / date_str
        sessions_data = []

        if day_dir.exists():
            session_files = list(day_dir.glob("session_*.json"))
            for session_file in session_files:
                try:
                    with open(session_file, 'r') as f:
                        sessions_data.append(json.load(f))
                except Exception as e:
                    print(f"⚠️ Failed to read session log {session_file}: {e}")

        # Calculate stats from session logs
        total_sessions = len(sessions_data)
        total_orders = 0
        total_fills = 0
        total_pnl = 0.0
        winning_trades = 0
        losing_trades = 0

        closed_sessions = []
        open_sessions = []

        for session_data in sessions_data:
            entries = session_data.get("entries", [])

            # Count orders and fills
            for entry in entries:
                if entry.get("type") == "order_submitted":
                    total_orders += 1
                elif entry.get("type") == "order_result":
                    if entry.get("status") == "FILLED":
                        total_fills += 1

            # Get session closure info
            session_closed_entry = next(
                (e for e in entries if e.get("type") == "session_closed"),
                None
            )

            if session_closed_entry:
                closed_sessions.append(session_data)
                final_pnl = session_closed_entry.get("final_pnl", 0.0)
                if final_pnl is not None:
                    total_pnl += final_pnl
                    if final_pnl > 0:
                        winning_trades += 1
                    elif final_pnl < 0:
                        losing_trades += 1
            else:
                open_sessions.append(session_data)

        # Build summary message
        text = f"<b>📊 DAILY TRADING SUMMARY</b>\n"
        text += f"<b>Date:</b> {date_str}\n\n"

        # Starting balance from snapshot
        if snapshot:
            text += f"<b>💰 Starting Balance:</b> ${starting_balance:,.2f}\n"
            snapshot_time = snapshot.get("timestamp", "")[:19].replace("T", " ")
            text += f"    <i>Snapshot: {snapshot_time} UTC ({snapshot.get('balance_source', 'UNKNOWN')})</i>\n"
        else:
            text += f"<b>⚠️ Starting Balance:</b> Not available (no snapshot taken)\n"
            text += f"    <i>Bot was not running at trading_hours_start</i>\n"

        # Current balance
        if account_balance is not None:
            text += f"<b>💰 Current Balance:</b> ${account_balance:,.2f}\n"
            if starting_balance is not None:
                daily_change = account_balance - starting_balance
                daily_pct = (daily_change / starting_balance) * 100 if starting_balance > 0 else 0
                emoji = "📈" if daily_change >= 0 else "📉"
                text += f"    {emoji} <b>Daily Change:</b> ${daily_change:+,.2f} ({daily_pct:+.2f}%)\n"

        text += "\n"

        # Performance stats
        total_closed = winning_trades + losing_trades
        win_rate_pct = (winning_trades / total_closed * 100) if total_closed > 0 else 0

        text += f"<b>📈 Performance</b>\n"
        text += f"• Total P&L: ${total_pnl:+,.2f}\n"
        if total_closed > 0:
            text += f"• Win Rate: {win_rate_pct:.1f}% ({winning_trades}/{total_closed})\n"
            text += f"• Winning Trades: {winning_trades}\n"
            text += f"• Losing Trades: {losing_trades}\n"
        else:
            text += f"• No closed trades\n"
        text += "\n"

        # Session stats
        text += f"<b>📋 Sessions</b>\n"
        text += f"• Total: {total_sessions}\n"
        text += f"• Closed: {len(closed_sessions)}\n"
        text += f"• Open: {len(open_sessions)}\n\n"

        # Activity stats
        text += f"<b>📊 Activity</b>\n"
        text += f"• Orders Submitted: {total_orders}\n"
        text += f"• Orders Filled: {total_fills}\n\n"

        # List closed positions
        if closed_sessions:
            text += f"<b>🔒 Closed Positions</b>\n"
            for session_data in closed_sessions[:5]:  # Show first 5
                # Extract session info from entries
                parsed_event = next(
                    (e for e in session_data.get("entries", []) if e.get("type") == "parsed_event"),
                    None
                )
                session_closed = next(
                    (e for e in session_data.get("entries", []) if e.get("type") == "session_closed"),
                    None
                )

                if parsed_event:
                    underlying = parsed_event.get("underlying", "?")
                    strike = parsed_event.get("strike", 0)
                    direction = parsed_event.get("direction", "?")
                    direction_short = direction[0] if direction else "?"
                    symbol = f"{underlying} {strike}{direction_short}"

                    pnl = session_closed.get("final_pnl", 0.0) if session_closed else 0.0
                    pnl_emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "⚪"
                    text += f"• {symbol} - {pnl_emoji} ${pnl:+.2f}\n"

            if len(closed_sessions) > 5:
                text += f"<i>... and {len(closed_sessions) - 5} more</i>\n"
            text += "\n"

        # List open positions
        if open_sessions:
            text += f"<b>🔓 Open Positions</b>\n"
            for session_data in open_sessions[:5]:  # Show first 5
                parsed_event = next(
                    (e for e in session_data.get("entries", []) if e.get("type") == "parsed_event"),
                    None
                )

                if parsed_event:
                    underlying = parsed_event.get("underlying", "?")
                    strike = parsed_event.get("strike", 0)
                    direction = parsed_event.get("direction", "?")
                    direction_short = direction[0] if direction else "?"
                    symbol = f"{underlying} {strike}{direction_short}"

                    # Count filled orders to get quantity
                    filled_orders = [
                        e for e in session_data.get("entries", [])
                        if e.get("type") == "order_result" and e.get("status") == "FILLED"
                    ]
                    qty = len(filled_orders)  # Simplified - each fill is 1 contract

                    text += f"• {symbol} - {qty} contracts\n"

            if len(open_sessions) > 5:
                text += f"<i>... and {len(open_sessions) - 5} more</i>\n"
            text += "\n"

        text += f"<i>Summary generated at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}</i>"

        await self.send_message(text)

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
        text += f"\n<i>Time: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}</i>"

        await self.send_message(text)

    def register_command_handler(self, command: str, handler):
        """
        Register a command handler function.

        Args:
            command: Command name without slash (e.g., "status")
            handler: Async function to handle the command
        """
        self.command_handlers[command] = handler

    async def poll_commands(self) -> List[Dict]:
        """
        Poll for new Telegram commands using getUpdates.

        Returns:
            List of command messages
        """
        if not self.enabled or not self.bot_token:
            return []

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
            params = {
                "timeout": 10,
                "allowed_updates": ["message"]
            }

            if self.last_update_id:
                params["offset"] = self.last_update_id + 1

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("ok") and data.get("result"):
                            updates = data["result"]

                            # Update last_update_id
                            if updates:
                                self.last_update_id = max(u["update_id"] for u in updates)

                            # Filter for commands from our chat
                            commands = []
                            for update in updates:
                                message = update.get("message", {})
                                text = message.get("text", "")
                                chat_id = str(message.get("chat", {}).get("id", ""))

                                # Only process messages from our chat
                                if chat_id == self.chat_id and text.startswith("/"):
                                    commands.append({
                                        "command": text.split()[0][1:],  # Remove leading /
                                        "args": text.split()[1:],
                                        "message": message
                                    })

                            return commands
                    return []
        except Exception as e:
            print(f"⚠️  Error polling Telegram commands: {e}")
            return []

    async def process_commands(self):
        """
        Poll and process Telegram commands.

        This should be called periodically in a background loop.
        """
        commands = await self.poll_commands()

        for cmd in commands:
            command_name = cmd["command"]
            handler = self.command_handlers.get(command_name)

            if handler:
                try:
                    # Call the handler
                    response = await handler(cmd)
                    if response:
                        await self.send_message(response)
                except Exception as e:
                    error_msg = f"❌ Error executing /{command_name}: {str(e)}"
                    await self.send_message(error_msg)
                    print(f"⚠️  Error executing /{command_name}: {e}")
            else:
                # Unknown command
                await self.send_message(f"❓ Unknown command: /{command_name}\n\nAvailable commands:\n📊 /status - Check positions and account\n🖥️ /server - Check bot and IBKR health")

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
