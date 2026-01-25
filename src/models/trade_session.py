from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from .enums import SessionState, PositionSide
from .event import Event


class Position(BaseModel):
    """Represents a single position within a trade session."""

    symbol: str  # Futures symbol (e.g., "MNQ")
    quantity: int
    entry_price: float
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: Optional[float] = None

    def is_open(self) -> bool:
        return self.exit_price is None


class TradeSession(BaseModel):
    """
    Represents a stateful trade session for futures trading.

    A session correlates related signals (NEW, ADD, EXIT, etc.)
    for the same trade idea. Session correlation rules:
    - Same author (signal source)
    - Same symbol (MNQ)
    - Same position side (LONG/SHORT)
    - Same trading day
    - Most recent open session wins
    """

    # Identification
    session_id: str
    state: SessionState = SessionState.PENDING

    # Trade definition
    author: str  # Signal source (e.g., "TradingView")
    symbol: str  # Futures symbol (e.g., "MNQ")
    position_side: PositionSide  # LONG or SHORT

    # Lifecycle
    created_at: datetime
    updated_at: datetime
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    # Events
    entry_event: Event  # The initial NEW event
    all_events: list[Event] = Field(default_factory=list)

    # Positions
    positions: list[Position] = Field(default_factory=list)

    # Risk and PnL
    total_quantity: int = 0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    # Order tracking
    entry_order_id: Optional[int] = None

    # Exit tracking
    exit_reason: Optional[str] = None  # "SIGNAL_EXIT", "MANUAL_EXIT", "FLIP_EXIT"
    exit_order_id: Optional[int] = None
    exit_price: Optional[float] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

    def add_event(self, event: Event) -> None:
        """Add an event to this session and update state."""
        event.session_id = self.session_id
        self.all_events.append(event)
        self.updated_at = datetime.now(timezone.utc)

        # State transitions
        if event.event_type.value == "NEW" and self.state == SessionState.PENDING:
            # NEW event opens the session when position is entered
            pass
        elif event.event_type.value == "CANCEL":
            self.state = SessionState.CANCELLED
        elif event.event_type.value in ["EXIT", "SL", "TP"]:
            if self.state == SessionState.OPEN:
                self.state = SessionState.CLOSED
                self.closed_at = datetime.now(timezone.utc)

    def is_active(self) -> bool:
        """Returns True if session is PENDING or OPEN."""
        return self.state in {SessionState.PENDING, SessionState.OPEN}

    def get_total_pnl(self) -> float:
        """Calculate total PnL (realized + unrealized)."""
        return self.realized_pnl + self.unrealized_pnl
