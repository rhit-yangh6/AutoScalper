"""
Test script for session manager.

Tests event correlation and session state management.
"""

from datetime import datetime
from src.orchestrator import SessionManager
from src.models import Event, EventType, Direction


def test_session_manager():
    """Test session manager with a sequence of events."""

    manager = SessionManager()

    print("="*70)
    print("TESTING SESSION MANAGER")
    print("="*70 + "\n")

    # Create test events
    events = [
        Event(
            event_type=EventType.NEW,
            timestamp=datetime.utcnow(),
            author="test_trader",
            message_id="msg_1",
            underlying="SPY",
            direction=Direction.CALL,
            strike=685.0,
            entry_price=0.43,
            targets=[686.0, 687.0],
            stop_loss=0.38,
            raw_message="bought SPY 685C @ 0.43",
        ),
        Event(
            event_type=EventType.TARGETS,
            timestamp=datetime.utcnow(),
            author="test_trader",
            message_id="msg_2",
            targets=[688.0],
            raw_message="new target 688",
        ),
        Event(
            event_type=EventType.ADD,
            timestamp=datetime.utcnow(),
            author="test_trader",
            message_id="msg_3",
            entry_price=0.35,
            quantity=1,
            raw_message="adding 1 @ 0.35",
        ),
        Event(
            event_type=EventType.EXIT,
            timestamp=datetime.utcnow(),
            author="test_trader",
            message_id="msg_4",
            raw_message="out @ 0.72",
        ),
    ]

    # Process events
    for i, event in enumerate(events, 1):
        print(f"\nEvent {i}: {event.event_type}")
        print("-" * 70)
        print(f"Message: {event.raw_message}")

        session = manager.process_event(event)

        if session:
            print(f"✓ Processed")
            print(f"  Session ID: {session.session_id[:8]}...")
            print(f"  State: {session.state}")
            print(f"  Events in session: {len(session.all_events)}")
            print(f"  Trade: {session.underlying} {session.strike} {session.direction}")
        else:
            print("  No session (event ignored)")

        print()

    # Check final state
    print("="*70)
    print("FINAL STATE")
    print("="*70)
    print(f"Total sessions: {len(manager.sessions)}")
    print(f"Active sessions: {len(manager.get_active_sessions())}")

    for session in manager.sessions.values():
        print(f"\nSession {session.session_id[:8]}...")
        print(f"  State: {session.state}")
        print(f"  Trade: {session.underlying} {session.strike} {session.direction}")
        print(f"  Events: {len(session.all_events)}")
        print(f"  Event types: {[e.event_type.value for e in session.all_events]}")

    print("\n" + "="*70)
    print("TESTING COMPLETE")
    print("="*70)


if __name__ == "__main__":
    test_session_manager()
