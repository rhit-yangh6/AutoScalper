"""
Test script for LLM parser.

Run this to test if the parser can correctly interpret Discord messages.
"""

import asyncio
from datetime import datetime
from src.llm_parser import LLMParser


async def test_parser():
    """Test the LLM parser with sample messages."""

    # Initialize parser (make sure ANTHROPIC_API_KEY is set)
    parser = LLMParser()

    # Sample Discord messages
    test_messages = [
        {
            "message": "bought SPY 685C @ 0.43, targeting 686 and 687, stop at 0.38",
            "author": "test_trader",
            "description": "NEW entry with targets and stop",
        },
        {
            "message": "adding 1 more @ 0.35, lowering avg",
            "author": "test_trader",
            "description": "ADD position",
        },
        {
            "message": "took off half @ 0.65",
            "author": "test_trader",
            "description": "TRIM partial exit",
        },
        {
            "message": "out @ 0.72, nice trade",
            "author": "test_trader",
            "description": "EXIT full",
        },
        {
            "message": "may add if we see a dip to 684",
            "author": "test_trader",
            "description": "PLAN intent",
        },
        {
            "message": "just chilling, waiting for setup",
            "author": "test_trader",
            "description": "IGNORE chatter",
        },
    ]

    print("="*70)
    print("TESTING LLM PARSER")
    print("="*70 + "\n")

    for i, test in enumerate(test_messages, 1):
        print(f"\nTest {i}: {test['description']}")
        print("-" * 70)
        print(f"Message: {test['message']}")
        print()

        try:
            event = parser.parse_message(
                message=test["message"],
                author=test["author"],
                message_id=f"test_{i}",
                timestamp=datetime.utcnow(),
            )

            print(f"✓ Parsed successfully")
            print(f"  Event Type: {event.event_type}")
            print(f"  Underlying: {event.underlying}")
            print(f"  Direction: {event.direction}")
            print(f"  Strike: {event.strike}")
            print(f"  Entry Price: {event.entry_price}")
            print(f"  Targets: {event.targets}")
            print(f"  Stop Loss: {event.stop_loss}")
            print(f"  Risk Level: {event.risk_level}")
            print(f"  Confidence: {event.parsing_confidence}")
            if event.llm_reasoning:
                print(f"  Reasoning: {event.llm_reasoning}")

        except Exception as e:
            print(f"✗ Parsing failed: {e}")

        print()

    print("="*70)
    print("TESTING COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(test_parser())
