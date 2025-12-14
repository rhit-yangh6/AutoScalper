import asyncio
import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

from ..llm_parser import LLMParser
from ..risk_gate import RiskGate, RiskDecision
from ..execution import ExecutionEngine
from ..discord_listener import DiscordListener
from .session_manager import SessionManager
from ..models import Event, EventType


class TradingOrchestrator:
    """
    Main orchestrator that coordinates all components.

    Flow:
    1. Discord message received
    2. LLM parses to Event
    3. Session manager correlates Event to TradeSession
    4. Risk gate validates
    5. Execution engine executes (if approved)
    """

    def __init__(self, config: dict):
        self.config = config

        # Initialize components
        print("Initializing Trading Orchestrator...")

        self.parser = LLMParser(
            api_key=config["anthropic_api_key"],
            model=config.get("llm_model", "claude-opus-4-5-20251101"),
        )

        self.session_manager = SessionManager()

        self.risk_gate = RiskGate(config["risk"])

        self.executor = ExecutionEngine(
            host=config["ibkr"]["host"],
            port=config["ibkr"]["port"],
            client_id=config["ibkr"]["client_id"],
        )

        self.discord_listener = DiscordListener(
            token=config["discord"]["user_token"],
            channel_ids=config["discord"]["channel_ids"],
            monitored_users=config["discord"].get("monitored_users"),
            message_callback=self.on_discord_message,
        )

        # State
        self.running = False
        self.paper_mode = config.get("paper_mode", True)

        print(
            f"Orchestrator initialized (paper_mode={self.paper_mode})"
        )

    async def start(self):
        """Start the orchestrator."""
        print("\n" + "=" * 60)
        print("STARTING AUTOSCALPER")
        print("=" * 60)
        print(f"Mode: {'PAPER TRADING' if self.paper_mode else 'LIVE TRADING'}")
        print(f"Risk per trade: {self.config['risk']['risk_per_trade_percent']}%")
        print(f"Daily max loss: {self.config['risk']['daily_max_loss_percent']}%")
        print(f"Max contracts: {self.config['risk']['max_contracts']}")
        print("=" * 60 + "\n")

        self.running = True

        # Connect to IBKR
        print("Connecting to IBKR...")
        connected = await self.executor.connect()
        if not connected:
            print("ERROR: Failed to connect to IBKR. Exiting.")
            return

        # Start Discord listener
        print("Starting Discord listener...")
        asyncio.create_task(self.discord_listener.start())

        # Keep running
        try:
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nShutdown requested...")
        finally:
            await self.stop()

    async def stop(self):
        """Stop the orchestrator."""
        print("\nStopping orchestrator...")
        self.running = False

        await self.discord_listener.stop()
        await self.executor.disconnect()

        print("Orchestrator stopped.")

    async def on_discord_message(
        self, message: str, author: str, message_id: str, timestamp: datetime
    ):
        """
        Callback for Discord messages.

        This is the main processing pipeline.
        """
        try:
            print(f"\n{'='*60}")
            print(f"NEW MESSAGE from {author}")
            print(f"{'='*60}")
            print(f"{message}\n")

            # Step 1: Parse message to Event
            print("[1/5] Parsing message with LLM...")
            try:
                event = self.parser.parse_message(
                    message=message,
                    author=author,
                    message_id=message_id,
                    timestamp=timestamp,
                )
                print(f"✓ Parsed as {event.event_type}")
                if event.llm_reasoning:
                    print(f"  Reasoning: {event.llm_reasoning}")
            except Exception as e:
                print(f"✗ Parsing failed: {e}")
                print("  ACTION: NO TRADE (parsing failure)")
                return

            # Step 2: Correlate to session
            print("\n[2/5] Correlating to trade session...")
            session = self.session_manager.process_event(event)

            if not session:
                print("✓ Event processed (non-actionable or ignored)")
                return

            print(f"✓ Linked to session {session.session_id[:8]}...")
            print(f"  Session state: {session.state}")
            print(f"  Trade: {session.underlying} {session.strike} {session.direction}")

            # Step 3: Risk validation
            print("\n[3/5] Validating with risk gate...")
            risk_result = self.risk_gate.validate(
                event=event,
                session=session,
            )

            print(f"{'✓' if risk_result.decision == RiskDecision.APPROVE else '✗'} {risk_result.decision}: {risk_result.reason}")

            if risk_result.decision == RiskDecision.REJECT:
                print("  ACTION: NO TRADE (risk gate rejection)")
                if risk_result.failed_checks:
                    for check in risk_result.failed_checks:
                        print(f"    - {check}")
                return

            # Step 4: Calculate position size and stops/targets
            print("\n[4/5] Calculating position size and risk parameters...")
            if event.is_actionable():
                quantity = self.risk_gate.calculate_position_size(
                    event=event, session=session
                )
                print(f"✓ Position size: {quantity} contracts")

                # Calculate stop loss and target if not provided
                if event.event_type == EventType.NEW:
                    stop_loss, target = self.risk_gate.calculate_stop_and_target(
                        event=event, session=session
                    )

                    # Update event with calculated values
                    if stop_loss and not event.stop_loss:
                        event.stop_loss = stop_loss
                        print(f"  Auto-calculated Stop Loss: ${stop_loss:.2f}")

                    if target and not event.targets:
                        event.targets = [target]
                        print(f"  Auto-calculated Target: ${target:.2f}")

                    # Show risk/reward
                    if event.entry_price and event.stop_loss and event.targets:
                        risk_per_contract = event.entry_price - event.stop_loss
                        reward_per_contract = event.targets[0] - event.entry_price
                        rr_ratio = reward_per_contract / risk_per_contract if risk_per_contract > 0 else 0
                        print(f"  Risk/Reward: 1:{rr_ratio:.2f}")
            else:
                print("✓ Non-actionable event (informational only)")
                return

            # Step 5: Execute
            print("\n[5/5] Executing order...")

            if self.paper_mode:
                print("  [PAPER MODE] Would execute:")
                print(f"    Event: {event.event_type}")
                print(f"    Quantity: {quantity}")
                print(f"    Entry: ${event.entry_price}")
                if event.targets:
                    print(f"    Targets: {event.targets}")
                if event.stop_loss:
                    print(f"    Stop: ${event.stop_loss}")
                print("  ACTION: SIMULATED (paper trading)")
            else:
                result = await self.executor.execute_event(
                    event=event,
                    session=session,
                    quantity=quantity,
                )

                if result.success:
                    print(f"✓ Order executed successfully")
                    print(f"  Order ID: {result.order_id}")
                    print(f"  Filled at: ${result.filled_price}")
                else:
                    print(f"✗ Execution failed: {result.message}")

            print(f"\n{'='*60}\n")

        except Exception as e:
            print(f"\nCRITICAL ERROR in message processing: {e}")
            print("ACTION: NO TRADE (system error)")
            import traceback

            traceback.print_exc()


async def main():
    """Main entry point."""
    # Load environment variables
    load_dotenv()

    # Build config (in production, load from YAML)
    config = {
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY"),
        "discord": {
            "user_token": os.getenv("DISCORD_USER_TOKEN"),
            "channel_ids": [
                int(x)
                for x in os.getenv("DISCORD_CHANNEL_IDS", "").split(",")
                if x
            ],
            "monitored_users": os.getenv("DISCORD_MONITORED_USERS", "").split(
                ","
            )
            if os.getenv("DISCORD_MONITORED_USERS")
            else None,
        },
        "ibkr": {
            "host": os.getenv("IBKR_HOST", "127.0.0.1"),
            "port": int(os.getenv("IBKR_PORT", "7497")),  # 7497 = paper
            "client_id": int(os.getenv("IBKR_CLIENT_ID", "1")),
        },
        "risk": {
            "account_balance": float(
                os.getenv("ACCOUNT_BALANCE", "10000")
            ),
            "risk_per_trade_percent": float(
                os.getenv("RISK_PER_TRADE_PERCENT", "0.5")
            ),
            "daily_max_loss_percent": float(
                os.getenv("DAILY_MAX_LOSS_PERCENT", "2.0")
            ),
            "max_loss_streak": int(os.getenv("MAX_LOSS_STREAK", "3")),
            "max_contracts": int(os.getenv("MAX_CONTRACTS", "1")),
            "max_adds_per_trade": int(os.getenv("MAX_ADDS_PER_TRADE", "1")),
            "trading_hours_start": os.getenv(
                "TRADING_HOURS_START", "13:30"
            ),  # 9:30 AM ET
            "trading_hours_end": os.getenv(
                "TRADING_HOURS_END", "20:00"
            ),  # 4:00 PM ET
            "max_bid_ask_spread_percent": float(
                os.getenv("MAX_BID_ASK_SPREAD_PERCENT", "10.0")
            ),
            "high_risk_size_reduction": float(
                os.getenv("HIGH_RISK_SIZE_REDUCTION", "0.5")
            ),
            "extreme_risk_size_reduction": float(
                os.getenv("EXTREME_RISK_SIZE_REDUCTION", "0.25")
            ),
            # Auto stop loss and targets
            "auto_stop_loss_percent": float(
                os.getenv("AUTO_STOP_LOSS_PERCENT", "25.0")
            ),
            "risk_reward_ratio": float(
                os.getenv("RISK_REWARD_RATIO", "2.0")
            ),
        },
        "paper_mode": os.getenv("PAPER_MODE", "true").lower() == "true",
    }

    # Create and start orchestrator
    orchestrator = TradingOrchestrator(config)
    await orchestrator.start()


if __name__ == "__main__":
    asyncio.run(main())
