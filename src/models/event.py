from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from .enums import EventType, Direction, RiskLevel


class Event(BaseModel):
    """
    Represents a single parsed Discord message event.

    This is the structured output of the LLM parser. Each Discord message
    becomes one Event, which is then linked to a TradeSession.
    """

    # Core identification
    event_type: EventType
    timestamp: datetime
    author: str  # Discord username
    message_id: str  # Discord message ID for idempotency

    # Trade details (populated based on event type)
    underlying: Optional[str] = None  # "SPY" or "SPXW"
    direction: Optional[Direction] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None  # ISO date string for the option expiry

    # Pricing
    entry_price: Optional[float] = None
    targets: Optional[list[float]] = Field(default=None)  # Multiple target prices
    stop_loss: Optional[float] = None

    # Position sizing
    quantity: Optional[int] = None  # Number of contracts

    # Risk assessment
    risk_level: Optional[RiskLevel] = None
    risk_notes: Optional[str] = None  # Free-form risk commentary

    # Context
    raw_message: str  # Original Discord message text
    session_id: Optional[str] = None  # Linked session (set after correlation)

    # Metadata
    parsing_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    llm_reasoning: Optional[str] = None  # LLM's explanation of its parse

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

    def is_actionable(self) -> bool:
        """Returns True if this event should trigger execution logic."""
        actionable_types = {
            EventType.NEW,
            EventType.ADD,
            EventType.TRIM,
            EventType.MOVE_STOP,
            EventType.TP,
            EventType.SL,
            EventType.EXIT,
        }
        return self.event_type in actionable_types

    def requires_position_open(self) -> bool:
        """Returns True if this event requires an open position."""
        return self.event_type in {
            EventType.ADD,
            EventType.TRIM,
            EventType.MOVE_STOP,
            EventType.TP,
            EventType.SL,
            EventType.EXIT,
        }
