import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from ..models import Event, TradeSession, EventType, SessionState


class SessionManager:
    """
    Manages trade sessions and correlates events to sessions.

    Correlation rules:
    - CRITICAL: Only ONE active session per author at any time
    - If author has active session, NEW events for different trades are REJECTED
    - UPDATE events (ADD, TRIM, EXIT, etc.) correlate to the active session
    - Session must be closed before starting a new trade
    """

    def __init__(self):
        self.sessions: dict[str, TradeSession] = {}

    def process_event(self, event: Event) -> Optional[TradeSession]:
        """
        Process an event and link it to appropriate session.

        Returns the updated/created session, or None if event should be ignored.
        """
        # Ignore non-actionable events at session level
        if event.event_type == EventType.IGNORE:
            return None

        # CANCEL or NEW events might create new sessions
        if event.event_type == EventType.NEW:
            return self._handle_new_event(event)
        elif event.event_type == EventType.CANCEL:
            return self._handle_cancel_event(event)
        else:
            # All other events need to correlate to existing session
            return self._handle_update_event(event)

    def _handle_new_event(self, event: Event) -> TradeSession:
        """Handle a NEW event by creating a new session."""
        # Validate required fields
        if not all([event.underlying, event.direction, event.strike]):
            raise ValueError(
                f"NEW event missing required fields: {event.raw_message}"
            )

        # CRITICAL: Only allow ONE active session at a time per author
        # Check for ANY active session for this author
        active_sessions = [
            s for s in self.sessions.values()
            if s.author == event.author and s.is_active()
        ]

        if active_sessions:
            # Found active session(s) - check if it matches this trade
            matching = self._find_matching_session(event)
            if matching:
                # Same trade - link to existing session instead of creating new one
                print(f"⚠️ Linking NEW event to existing active session (duplicate NEW for same trade)")
                matching.add_event(event)
                return matching
            else:
                # Different trade - reject NEW event (only one active session allowed)
                existing_session = active_sessions[0]
                symbol = f"{existing_session.underlying} {existing_session.strike}{existing_session.direction.value[0]}"
                print(f"⚠️ Cannot create new session - already have active session: {symbol}")
                print(f"⚠️ Close existing position before opening new one")
                raise ValueError(
                    f"Only one active session allowed at a time. "
                    f"Current active: {symbol} (session {existing_session.session_id[:8]}...)"
                )

        # No active sessions - safe to create new session
        session_id = self._generate_session_id()
        session = TradeSession(
            session_id=session_id,
            state=SessionState.PENDING,
            author=event.author,
            underlying=event.underlying,
            direction=event.direction,
            strike=event.strike,
            expiry=event.expiry or self._get_today_expiry(),
            created_at=event.timestamp,
            updated_at=event.timestamp,
            entry_event=event,
        )
        session.add_event(event)
        self.sessions[session_id] = session
        return session

    def _handle_cancel_event(self, event: Event) -> Optional[TradeSession]:
        """Handle a CANCEL event."""
        session = self._find_matching_session(event)
        if session and session.is_active():
            session.add_event(event)
            return session
        return None

    def _handle_update_event(self, event: Event) -> Optional[TradeSession]:
        """
        Handle ADD, TRIM, EXIT, TP, SL, MOVE_STOP, TARGETS, etc.

        These all require an existing active session.
        """
        session = self._find_matching_session(event)

        if not session:
            # No matching session - this is a failure case
            # Could be orphaned message or out-of-order delivery
            print(
                f"WARNING: Event {event.event_type} has no matching session: {event.raw_message}"
            )
            return None

        if not session.is_active():
            print(
                f"WARNING: Event {event.event_type} targets inactive session {session.session_id}"
            )
            return None

        # Add event to session
        session.add_event(event)
        return session

    def _session_matches_event(self, session: TradeSession, event: Event) -> bool:
        """Check if session matches event criteria."""
        return (
            session.is_active() and
            session.author == event.author and
            (not event.underlying or session.underlying == event.underlying) and
            (not event.direction or session.direction == event.direction) and
            session.created_at.date() == event.timestamp.date()
        )

    def _find_matching_session(self, event: Event) -> Optional[TradeSession]:
        """Find the most recent active session matching this event."""
        candidates = [
            s for s in self.sessions.values()
            if self._session_matches_event(s, event)
        ]

        return max(candidates, key=lambda s: s.updated_at) if candidates else None

    def get_session(self, session_id: str) -> Optional[TradeSession]:
        """Get session by ID."""
        return self.sessions.get(session_id)

    def get_active_sessions(self) -> list[TradeSession]:
        """Get all currently active sessions."""
        return [s for s in self.sessions.values() if s.is_active()]

    def get_sessions_by_author(self, author: str) -> list[TradeSession]:
        """Get all sessions for a given author."""
        return [s for s in self.sessions.values() if s.author == author]

    def _generate_session_id(self) -> str:
        """Generate unique session ID."""
        return str(uuid.uuid4())

    def _get_today_expiry(self) -> str:
        """Get today's date as expiry (for 0DTE)."""
        return datetime.now(timezone.utc).date().isoformat()

    def get_sessions_for_date_str(self, date_str: str) -> list:
        """
        Get all sessions for a specific date.

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            List of sessions created on that date
        """
        target_date = datetime.fromisoformat(date_str).date()

        return [
            s for s in self.sessions.values()
            if s.created_at.date() == target_date
        ]

    def cleanup_old_sessions(self, days: int = 7) -> int:
        """
        Remove sessions older than specified days.

        Returns number of sessions removed.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        old_sessions = [
            sid
            for sid, session in self.sessions.items()
            if session.updated_at < cutoff
        ]

        for sid in old_sessions:
            del self.sessions[sid]

        return len(old_sessions)
