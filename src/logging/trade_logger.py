"""
Trade logging system for Discord messages and IBKR orders.

Logs are organized by:
- Trading day
- Trading session (each NEW event creates a new session log)
- Discord messages (raw and parsed)
- Orders (submitted, filled, cancelled, rejected)
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from enum import Enum

from ..models import Event, TradeSession, EventType
from ..execution.executor import OrderResult, OrderStatus


class LogLevel(str, Enum):
    """Log levels for filtering."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class TradeLogger:
    """
    Comprehensive logging for trading activity.

    Creates organized logs:
    - logs/YYYY-MM-DD/session_HHMMSS_SYMBOL_DIRECTION.log (human-readable)
    - logs/YYYY-MM-DD/session_HHMMSS_SYMBOL_DIRECTION.json (structured)
    - logs/YYYY-MM-DD/all_messages.log (all Discord messages)
    - logs/YYYY-MM-DD/all_orders.log (all orders)
    """

    def __init__(self, base_dir: str = "logs"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)

        # Track current session log files
        self.session_logs: dict[str, dict] = {}  # session_id -> {txt_path, json_path, entries}

        # Current day directory
        self.current_day_dir: Optional[Path] = None
        self._update_day_directory()

    def _update_day_directory(self):
        """Create/update directory for today's logs."""
        today = datetime.now().strftime('%Y-%m-%d')
        self.current_day_dir = self.base_dir / today
        self.current_day_dir.mkdir(exist_ok=True)

    def _get_session_log_files(self, session: TradeSession) -> tuple[Path, Path]:
        """Get or create log file paths for a session."""
        # Check if we need to update day directory
        if not self.current_day_dir or self.current_day_dir.name != datetime.now().strftime('%Y-%m-%d'):
            self._update_day_directory()

        # If session already has log files, return them
        if session.session_id in self.session_logs:
            logs = self.session_logs[session.session_id]
            return logs['txt_path'], logs['json_path']

        # Create new log files for this session
        timestamp = session.created_at.strftime('%H%M%S')
        symbol = session.underlying or "UNKNOWN"
        direction = session.direction.value if session.direction else "UNKNOWN"

        base_name = f"session_{timestamp}_{symbol}_{direction}"
        txt_path = self.current_day_dir / f"{base_name}.log"
        json_path = self.current_day_dir / f"{base_name}.json"

        # Initialize session log
        self.session_logs[session.session_id] = {
            'txt_path': txt_path,
            'json_path': json_path,
            'entries': []
        }

        # Write header to text log
        with open(txt_path, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write(f"TRADING SESSION: {session.session_id}\n")
            f.write(f"Started: {session.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            f.write(f"Symbol: {symbol} {direction}\n")
            f.write(f"Strike: {session.strike} Expiry: {session.expiry}\n")
            f.write("=" * 80 + "\n\n")

        return txt_path, json_path

    def log_discord_message(
        self,
        session: Optional[TradeSession],
        author: str,
        message: str,
        timestamp: datetime,
        message_id: str,
    ):
        """
        Log a Discord message.

        Logs to both:
        - Session-specific log (if session exists)
        - All messages log for the day
        """
        # Update day directory if needed
        if not self.current_day_dir or self.current_day_dir.name != datetime.now().strftime('%Y-%m-%d'):
            self._update_day_directory()

        # Format message
        time_str = timestamp.strftime('%H:%M:%S')
        log_entry = f"[{time_str}] {author}: {message}\n"

        # Log to all_messages.log
        all_messages_path = self.current_day_dir / "all_messages.log"
        with open(all_messages_path, 'a') as f:
            f.write(log_entry)

        # Log to session-specific log if session exists
        if session:
            txt_path, json_path = self._get_session_log_files(session)

            # Append to text log
            with open(txt_path, 'a') as f:
                f.write(f"[DISCORD MESSAGE]\n")
                f.write(log_entry)
                f.write(f"  Message ID: {message_id}\n\n")

            # Add to JSON entries
            self.session_logs[session.session_id]['entries'].append({
                'type': 'discord_message',
                'timestamp': timestamp.isoformat(),
                'author': author,
                'message': message,
                'message_id': message_id
            })

    def log_parsed_event(
        self,
        session: Optional[TradeSession],
        event: Event,
    ):
        """Log a parsed event from LLM."""
        if not session:
            return

        txt_path, json_path = self._get_session_log_files(session)

        # Format for text log
        with open(txt_path, 'a') as f:
            f.write(f"[PARSED EVENT: {event.event_type.value}]\n")
            f.write(f"  Confidence: {event.parsing_confidence:.2f}\n")
            if event.llm_reasoning:
                f.write(f"  Reasoning: {event.llm_reasoning}\n")

            # Event details
            if event.entry_price:
                f.write(f"  Entry Price: ${event.entry_price:.2f}\n")
            if event.stop_loss:
                f.write(f"  Stop Loss: ${event.stop_loss:.2f}\n")
            if event.targets:
                f.write(f"  Targets: {', '.join(f'${t:.2f}' for t in event.targets)}\n")
            if event.quantity:
                f.write(f"  Quantity: {event.quantity}\n")
            if event.risk_level:
                f.write(f"  Risk Level: {event.risk_level.value}\n")
            if event.risk_notes:
                f.write(f"  Risk Notes: {event.risk_notes}\n")

            f.write("\n")

        # Add to JSON entries
        self.session_logs[session.session_id]['entries'].append({
            'type': 'parsed_event',
            'timestamp': event.timestamp.isoformat(),
            'event_type': event.event_type.value,
            'entry_price': event.entry_price,
            'stop_loss': event.stop_loss,
            'targets': event.targets,
            'quantity': event.quantity,
            'risk_level': event.risk_level.value if event.risk_level else None,
            'risk_notes': event.risk_notes,
            'parsing_confidence': event.parsing_confidence,
            'llm_reasoning': event.llm_reasoning
        })

    def log_order_submitted(
        self,
        session: TradeSession,
        event_type: EventType,
        order_details: dict,
    ):
        """Log an order submission to IBKR."""
        txt_path, json_path = self._get_session_log_files(session)

        timestamp = datetime.now(timezone.utc)
        time_str = timestamp.strftime('%H:%M:%S')

        # Format for text log
        with open(txt_path, 'a') as f:
            f.write(f"[{time_str}] [ORDER SUBMITTED: {event_type.value}]\n")
            for key, value in order_details.items():
                f.write(f"  {key}: {value}\n")
            f.write("\n")

        # Log to all_orders.log
        all_orders_path = self.current_day_dir / "all_orders.log"
        with open(all_orders_path, 'a') as f:
            f.write(f"[{time_str}] [{event_type.value}] SUBMITTED\n")
            for key, value in order_details.items():
                f.write(f"  {key}: {value}\n")
            f.write("\n")

        # Add to JSON entries
        self.session_logs[session.session_id]['entries'].append({
            'type': 'order_submitted',
            'timestamp': timestamp.isoformat(),
            'event_type': event_type.value,
            'order_details': order_details
        })

    def log_order_result(
        self,
        session: TradeSession,
        event_type: EventType,
        result: OrderResult,
    ):
        """Log the result of an order execution."""
        txt_path, json_path = self._get_session_log_files(session)

        timestamp = datetime.now(timezone.utc)
        time_str = timestamp.strftime('%H:%M:%S')

        # result.status is already a string value (Pydantic's use_enum_values = True)
        # Determine status emoji based on string value
        status_symbol = {
            "FILLED": "✓",
            "CANCELLED": "✗",
            "REJECTED": "⚠",
            "PENDING": "⏳",
            "SUBMITTED": "→"
        }.get(result.status, "?")

        # Format for text log
        with open(txt_path, 'a') as f:
            f.write(f"[{time_str}] [ORDER RESULT: {event_type.value}] {status_symbol} {result.status}\n")
            if result.order_id:
                f.write(f"  Order ID: {result.order_id}\n")
            if result.filled_price:
                f.write(f"  Filled Price: ${result.filled_price:.2f}\n")
            if result.message:
                f.write(f"  Message: {result.message}\n")
            f.write(f"  Success: {result.success}\n\n")

        # Log to all_orders.log
        all_orders_path = self.current_day_dir / "all_orders.log"
        with open(all_orders_path, 'a') as f:
            f.write(f"[{time_str}] [{event_type.value}] {status_symbol} {result.status}\n")
            if result.order_id:
                f.write(f"  Order ID: {result.order_id}\n")
            if result.filled_price:
                f.write(f"  Filled Price: ${result.filled_price:.2f}\n")
            if result.message:
                f.write(f"  Message: {result.message}\n")
            f.write("\n")

        # Add to JSON entries
        self.session_logs[session.session_id]['entries'].append({
            'type': 'order_result',
            'timestamp': timestamp.isoformat(),
            'event_type': event_type.value,
            'status': result.status,
            'success': result.success,
            'order_id': result.order_id,
            'filled_price': result.filled_price,
            'message': result.message
        })

    def log_session_closed(
        self,
        session: TradeSession,
        reason: str,
        final_pnl: Optional[float] = None,
    ):
        """Log session closure."""
        txt_path, json_path = self._get_session_log_files(session)

        timestamp = datetime.now(timezone.utc)

        # Write footer to text log
        with open(txt_path, 'a') as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"SESSION CLOSED: {reason}\n")
            f.write(f"Closed at: {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            if final_pnl is not None:
                pnl_symbol = "+" if final_pnl >= 0 else ""
                f.write(f"Final P&L: {pnl_symbol}${final_pnl:.2f}\n")
            f.write(f"Total Events: {len(session.events)}\n")
            f.write(f"Total Quantity: {session.total_quantity}\n")
            f.write("=" * 80 + "\n")

        # Add to JSON entries
        self.session_logs[session.session_id]['entries'].append({
            'type': 'session_closed',
            'timestamp': timestamp.isoformat(),
            'reason': reason,
            'final_pnl': final_pnl,
            'total_events': len(session.events),
            'total_quantity': session.total_quantity
        })

        # Write complete JSON log
        self._write_json_log(session.session_id)

    def log_error(
        self,
        session: Optional[TradeSession],
        error_type: str,
        error_message: str,
    ):
        """Log an error."""
        timestamp = datetime.now(timezone.utc)
        time_str = timestamp.strftime('%H:%M:%S')

        # Log to day's error log
        if not self.current_day_dir or self.current_day_dir.name != datetime.now().strftime('%Y-%m-%d'):
            self._update_day_directory()

        error_log_path = self.current_day_dir / "errors.log"
        with open(error_log_path, 'a') as f:
            f.write(f"[{time_str}] [{error_type}] {error_message}\n")

        # Also log to session if exists
        if session:
            txt_path, _ = self._get_session_log_files(session)
            with open(txt_path, 'a') as f:
                f.write(f"[{time_str}] [ERROR: {error_type}]\n")
                f.write(f"  {error_message}\n\n")

            self.session_logs[session.session_id]['entries'].append({
                'type': 'error',
                'timestamp': timestamp.isoformat(),
                'error_type': error_type,
                'error_message': error_message
            })

    def _write_json_log(self, session_id: str):
        """Write the complete JSON log for a session."""
        if session_id not in self.session_logs:
            return

        logs = self.session_logs[session_id]
        json_path = logs['json_path']

        with open(json_path, 'w') as f:
            json.dump({
                'session_id': session_id,
                'entries': logs['entries']
            }, f, indent=2)

    def flush_session(self, session_id: str):
        """Flush and finalize a session's JSON log."""
        if session_id in self.session_logs:
            self._write_json_log(session_id)

    def flush_all(self):
        """Flush all session JSON logs."""
        for session_id in self.session_logs:
            self._write_json_log(session_id)


# Global logger instance
_logger: Optional[TradeLogger] = None


def get_logger() -> TradeLogger:
    """Get the global trade logger instance."""
    global _logger
    if _logger is None:
        _logger = TradeLogger()
    return _logger


def init_logger(base_dir: str = "logs") -> TradeLogger:
    """Initialize the global trade logger."""
    global _logger
    _logger = TradeLogger(base_dir=base_dir)
    return _logger
