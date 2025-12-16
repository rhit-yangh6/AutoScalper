from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from .enums import SessionState, Direction
from .event import Event


class Position(BaseModel):
    """Represents a single position within a trade session."""

    contract_symbol: str  # Full option symbol
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
    Represents a stateful trade session composed of multiple events.

    A session correlates related Discord messages (NEW, ADD, EXIT, etc.)
    for the same trade idea. Session correlation rules:
    - Same author
    - Same underlying (SPY/SPX)
    - Same direction (CALL/PUT)
    - Same trading day
    - Most recent open session wins
    """

    # Identification
    session_id: str
    state: SessionState = SessionState.PENDING

    # Trade definition
    author: str  # Discord username who initiated the trade
    underlying: str  # "SPY" or "SPXW"
    direction: Direction
    strike: float
    expiry: str  # ISO date string

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

    # Order tracking (for bracket monitoring)
    entry_order_id: Optional[int] = None
    stop_order_id: Optional[int] = None
    target_order_ids: list[int] = Field(default_factory=list)

    # Exit tracking
    exit_reason: Optional[str] = None  # "STOP_HIT", "TARGET_HIT", "MANUAL_EXIT"
    exit_order_id: Optional[int] = None
    exit_price: Optional[float] = None

    # Controls
    max_adds: int = 1  # From config, default from proposal
    num_adds: int = 0
    stop_invalidated: bool = False  # True if stop was hit

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
        elif event.event_type.value == "ADD":
            self.num_adds += 1

    def can_add_position(self) -> bool:
        """Check if we can add to this position based on rules."""
        if self.state != SessionState.OPEN:
            return False
        if self.num_adds >= self.max_adds:
            return False
        if self.stop_invalidated:
            return False
        return True

    def is_active(self) -> bool:
        """Returns True if session is PENDING or OPEN."""
        return self.state in {SessionState.PENDING, SessionState.OPEN}

    def get_total_pnl(self) -> float:
        """Calculate total PnL (realized + unrealized)."""
        return self.realized_pnl + self.unrealized_pnl
