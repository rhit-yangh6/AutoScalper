from enum import Enum


class EventType(str, Enum):
    """Types of events from TradingView webhook signals."""

    NEW = "NEW"  # New trade entry
    ADD = "ADD"  # Scale-in / add to position
    TP = "TP"  # Take profit triggered
    SL = "SL"  # Stop loss triggered
    EXIT = "EXIT"  # Manual exit / close position
    CLOSE_ALL = "CLOSE_ALL"  # Close all positions
    CANCEL = "CANCEL"  # Cancel pending entry
    IGNORE = "IGNORE"  # Non-actionable signal


class SessionState(str, Enum):
    """Lifecycle states of a trade session."""

    PENDING = "PENDING"  # Trade idea announced but not yet entered
    OPEN = "OPEN"  # Position is active
    CLOSED = "CLOSED"  # Position closed (TP, SL, or EXIT)
    CANCELLED = "CANCELLED"  # Trade invalidated before entry


class PositionSide(str, Enum):
    """Futures position side."""

    LONG = "LONG"
    SHORT = "SHORT"


class RiskLevel(str, Enum):
    """Risk assessment for a trade."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"  # Additional level for very risky setups
