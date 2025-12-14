from enum import Enum


class EventType(str, Enum):
    """Types of events that can be parsed from Discord messages."""

    NEW = "NEW"  # Initial trade idea
    PLAN = "PLAN"  # Intent or permission (e.g., may average down later)
    ADD = "ADD"  # Explicit scale-in or average-down action
    TARGETS = "TARGETS"  # Profit targets
    TRIM = "TRIM"  # Partial exit
    MOVE_STOP = "MOVE_STOP"  # Tighten stop
    TP = "TP"  # Target hit
    SL = "SL"  # Stop hit
    EXIT = "EXIT"  # Close entire position
    CANCEL = "CANCEL"  # Invalidate trade before entry
    RISK_NOTE = "RISK_NOTE"  # Contextual warning or commentary
    IGNORE = "IGNORE"  # Chatter or irrelevant message


class SessionState(str, Enum):
    """Lifecycle states of a trade session."""

    PENDING = "PENDING"  # Trade idea announced but not yet entered
    OPEN = "OPEN"  # Position is active
    CLOSED = "CLOSED"  # Position closed (TP, SL, or EXIT)
    CANCELLED = "CANCELLED"  # Trade invalidated before entry


class Direction(str, Enum):
    """Option direction."""

    CALL = "CALL"
    PUT = "PUT"


class RiskLevel(str, Enum):
    """Risk assessment for a trade."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"  # Additional level for very risky setups
