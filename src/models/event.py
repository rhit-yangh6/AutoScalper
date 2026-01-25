from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from .enums import EventType, PositionSide, RiskLevel


class Event(BaseModel):
    """
    Represents a trading signal event from TradingView webhook.

    This is the structured output from TradingView alerts.
    Each webhook becomes one Event, which is then linked to a TradeSession.
    """

    # Core identification
    event_type: EventType
    timestamp: datetime
    author: str  # Signal source (e.g., "TradingView")
    message_id: str  # Unique ID for idempotency

    # Futures trade details
    symbol: str = "MNQ"  # Futures symbol (MNQ, ES, NQ, etc.)
    position_side: Optional[PositionSide] = None  # LONG or SHORT

    # Pricing (optional, for reference only)
    entry_price: float = 0.0  # Entry price if provided

    # Position sizing
    quantity: int = 1  # Number of contracts

    # Risk assessment
    risk_level: Optional[RiskLevel] = None
    risk_notes: Optional[str] = None  # Free-form risk commentary

    # Context
    raw_message: str  # Original webhook payload
    session_id: Optional[str] = None  # Linked session (set after correlation)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

    def is_actionable(self) -> bool:
        """Returns True if this event should trigger execution logic."""
        actionable_types = {
            EventType.NEW,
            EventType.ADD,
            EventType.TP,
            EventType.SL,
            EventType.EXIT,
            EventType.CLOSE_ALL,
        }
        return self.event_type in actionable_types

    def requires_position_open(self) -> bool:
        """Returns True if this event requires an open position."""
        return self.event_type in {
            EventType.ADD,
            EventType.TP,
            EventType.SL,
            EventType.EXIT,
            EventType.CLOSE_ALL,
        }
