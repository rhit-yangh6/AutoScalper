import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from ..models import Event, TradeSession, EventType, SessionState


class SessionManager:
    """
    Manages trade sessions and correlates events to sessions.

    Correlation rules (from proposal):
    - Same author
    - Same underlying (SPY/SPX)
    - Same direction (CALL/PUT)
    - Same trading day
    - Most recent open session wins
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

        # Check if there's an existing active session we should link to
        # (edge case: user posts multiple NEW messages for same trade)
        existing = self._find_matching_session(event)
        if existing and existing.is_active():
            # Link to existing session instead of creating new one
            existing.add_event(event)
            return existing

        # Create new session
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

    def _find_matching_session(self, event: Event) -> Optional[TradeSession]:
        """
        Find the most recent active session matching this event.

        Correlation rules:
        - Same author
        - Same underlying
        - Same direction
        - Same trading day
        - Most recent wins
        """
        candidates = []

        for session in self.sessions.values():
            # Must be active
            if not session.is_active():
                continue

            # Same author
            if session.author != event.author:
                continue

            # Same underlying
            if event.underlying and session.underlying != event.underlying:
                continue

            # Same direction
            if event.direction and session.direction != event.direction:
                continue

            # Same trading day (compare dates only)
            if session.created_at.date() != event.timestamp.date():
                continue

            candidates.append(session)

        # Return most recent
        if candidates:
            return max(candidates, key=lambda s: s.updated_at)

        return None

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
