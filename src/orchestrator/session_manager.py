"""
Session Manager for MNQ Futures Trading

Manages trade sessions and correlates events to sessions.
Simplified for futures trading (no options complexity).
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from ..models import Event, TradeSession, EventType, SessionState, PositionSide


class SessionManager:
    """
    Manages trade sessions and correlates events to sessions.

    Correlation rules for futures:
    - Only ONE active session per author at any time
    - If author has active session, NEW events for different trades are REJECTED
    - UPDATE events (ADD, EXIT, etc.) correlate to the active session
    - Session must be closed before starting a new trade
    """

    def __init__(self):
        self.sessions: dict[str, TradeSession] = {}

    def check_for_flip(self, event: Event) -> Optional[TradeSession]:
        """
        Check if a NEW event would flip an existing position.

        Returns the session that needs to be closed first, or None if no flip.

        A flip occurs when:
        - NEW event for symbol X, side LONG
        - Active session exists for symbol X, side SHORT (or vice versa)
        """
        if event.event_type != EventType.NEW:
            return None

        if not event.position_side:
            return None

        # Find active sessions for same author and symbol but OPPOSITE side
        for session in self.sessions.values():
            if not session.is_active():
                continue
            if session.author != event.author:
                continue
            if session.symbol != event.symbol:
                continue
            # Check if opposite side
            if session.position_side != event.position_side:
                return session

        return None

    def process_event(self, event: Event) -> Optional[TradeSession]:
        """
        Process an event and link it to appropriate session.

        Returns the updated/created session, or None if event should be ignored.
        """
        if event.event_type == EventType.IGNORE:
            return None

        if event.event_type == EventType.NEW:
            return self._handle_new_event(event)
        elif event.event_type == EventType.CANCEL:
            return self._handle_cancel_event(event)
        else:
            return self._handle_update_event(event)

    def _handle_new_event(self, event: Event) -> TradeSession:
        """Handle a NEW event by creating a new session."""
        # Validate required fields
        if not all([event.symbol, event.position_side]):
            raise ValueError(
                f"NEW event missing required fields: symbol, position_side"
            )

        # Check for existing active session
        active_sessions = [
            s for s in self.sessions.values()
            if s.author == event.author and s.is_active()
        ]

        if active_sessions:
            # Check if it matches this trade (same symbol and side)
            matching = self._find_matching_session(event)
            if matching:
                # Same trade - convert NEW to ADD
                print(f"⚠️ Detected duplicate NEW signal for existing position")
                print(f"  Existing: {matching.symbol} {matching.position_side.value} @ ${matching.avg_entry_price:.2f}")
                print(f"  Converting NEW → ADD")

                event.event_type = EventType.ADD
                matching.add_event(event)
                return matching
            else:
                # Different trade - reject
                existing_session = active_sessions[0]
                symbol = f"{existing_session.symbol} {existing_session.position_side.value}"
                print(f"⚠️ Cannot create new session - already have active session: {symbol}")
                raise ValueError(
                    f"Only one active session allowed. Current: {symbol}"
                )

        # Create new session
        session_id = self._generate_session_id()
        session = TradeSession(
            session_id=session_id,
            state=SessionState.PENDING,
            author=event.author,
            symbol=event.symbol,
            position_side=event.position_side,
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
        Handle ADD, EXIT, TP, SL events.

        These require an existing active session.
        """
        session = self._find_matching_session(event)

        if not session:
            print(
                f"WARNING: Event {event.event_type} has no matching session"
            )
            return None

        if not session.is_active():
            print(
                f"WARNING: Event {event.event_type} targets inactive session {session.session_id}"
            )
            return None

        session.add_event(event)
        return session

    def _session_matches_event(self, session: TradeSession, event: Event) -> bool:
        """
        Check if session matches event criteria.

        For futures, checks:
        - Same author
        - Same symbol
        - Same position side (if provided)
        - Same trading day
        """
        if not session.is_active() or session.author != event.author:
            return False

        # Symbol check (allow None for update events like EXIT)
        if event.symbol and session.symbol != event.symbol:
            return False

        # Position side check (allow None for update events)
        if event.position_side and session.position_side != event.position_side:
            return False

        # Same trading day check
        if session.created_at.date() != event.timestamp.date():
            return False

        return True

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
