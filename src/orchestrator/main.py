import asyncio
import os
from datetime import datetime, time, timezone
from typing import Optional

from dotenv import load_dotenv

from ..llm_parser import LLMParser
from ..risk_gate import RiskGate, RiskDecision
from ..execution import ExecutionEngine
from ..discord_listener import DiscordListener
from .session_manager import SessionManager
from ..models import Event, EventType
from ..logging import init_logger, get_logger
from ..notifications import init_notifier, get_notifier


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

        # Initialize logger
        log_dir = config.get("log_dir", "logs")
        self.logger = init_logger(base_dir=log_dir)
        print(f"Logger initialized (log_dir={log_dir})")

        # Initialize Telegram notifier
        telegram_config = config.get("telegram", {})
        if telegram_config.get("enabled", False):
            self.notifier = init_notifier(
                bot_token=telegram_config.get("bot_token", ""),
                chat_id=telegram_config.get("chat_id", ""),
                enabled=True,
            )
            print("Telegram notifications enabled")
        else:
            self.notifier = None
            print("Telegram notifications disabled")

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

        # Connect to IBKR (only if not in paper mode)
        if not self.paper_mode:
            print("Connecting to IBKR...")
            connected = await self.executor.connect()
            if not connected:
                print("ERROR: Failed to connect to IBKR. Exiting.")
                return
        else:
            print("Skipping IBKR connection (paper mode - no orders will be sent)")

        # Start Discord listener
        print("Starting Discord listener...")
        asyncio.create_task(self.discord_listener.start())

        # Start daily summary task if Telegram enabled
        if self.notifier:
            print("Starting daily summary scheduler...")
            asyncio.create_task(self._daily_summary_task())

            # Register and start Telegram command polling
            print("Starting Telegram command handler...")
            self.notifier.register_command_handler("status", self._handle_status_command)
            asyncio.create_task(self._telegram_command_polling_task())

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

        # Only disconnect from IBKR if we connected
        if not self.paper_mode:
            await self.executor.disconnect()

        # Flush all logs
        print("Flushing logs...")
        self.logger.flush_all()

        print("Orchestrator stopped.")

    async def _daily_summary_task(self):
        """
        Background task that sends daily summary after trading hours end.

        Uses TRADING_HOURS_END from config (default: 20:00 UTC = 4:00 PM ET)
        """
        summary_time_str = self.config["risk"]["trading_hours_end"]
        try:
            hour, minute = map(int, summary_time_str.split(":"))
            summary_time = time(hour=hour, minute=minute)
        except:
            # Default to 8 PM UTC (4 PM ET)
            summary_time = time(hour=20, minute=0)

        print(f"Daily summary will be sent at {summary_time_str} UTC (after trading hours close)")

        while self.running:
            now = datetime.now(timezone.utc)
            target_time = datetime.combine(now.date(), summary_time, tzinfo=timezone.utc)

            # If target time already passed today, schedule for tomorrow
            if now > target_time:
                from datetime import timedelta
                target_time += timedelta(days=1)

            # Calculate seconds until target time
            seconds_until_summary = (target_time - now).total_seconds()

            # Wait until summary time
            await asyncio.sleep(seconds_until_summary)

            # Send daily summary
            if self.running and self.notifier:
                try:
                    print(f"\nSending daily summary at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}...")

                    # Get all sessions for today
                    all_sessions = list(self.session_manager.sessions.values())

                    # Get account balance if connected to IBKR
                    account_balance = None
                    if not self.paper_mode and self.executor.connected:
                        account_balance = await self.executor.get_account_balance()

                    await self.notifier.send_daily_summary(all_sessions, account_balance)

                    print("✓ Daily summary sent")
                except Exception as e:
                    print(f"✗ Failed to send daily summary: {e}")

            # Wait a bit to avoid sending multiple times
            await asyncio.sleep(60)

    async def _telegram_command_polling_task(self):
        """
        Background task that polls for Telegram commands.

        Checks for commands every 5 seconds.
        """
        print("Telegram command polling active (send /status to check positions)")

        while self.running:
            try:
                await self.notifier.process_commands()
                await asyncio.sleep(5)  # Poll every 5 seconds
            except Exception as e:
                print(f"⚠️  Error in Telegram command polling: {e}")
                await asyncio.sleep(5)

    async def _handle_status_command(self, cmd: dict) -> str:
        """
        Handle /status command from Telegram.

        Returns formatted status message with positions and account info.
        """
        try:
            mode = "📝 PAPER" if self.paper_mode else "🔴 LIVE"

            # Get account balance
            account_balance = None
            if not self.paper_mode and self.executor.connected:
                account_balance = await self.executor.get_account_balance()

            # Get positions
            positions = []
            if not self.paper_mode and self.executor.connected:
                positions = await self.executor.get_positions()

            # Get open orders
            open_orders = []
            if not self.paper_mode and self.executor.connected:
                open_orders = await self.executor.get_open_orders()

            # Get active sessions
            open_sessions = [s for s in self.session_manager.sessions.values() if s.state == "OPEN"]

            # Build response
            text = f"<b>📊 {mode} STATUS</b>\n\n"

            # Account balance
            if account_balance:
                text += f"<b>💰 Account Balance:</b> ${account_balance:,.2f}\n\n"
            else:
                text += f"<b>💰 Account Balance:</b> Not available\n\n"

            # Positions
            text += f"<b>🔓 Open Positions ({len(positions)}):</b>\n"
            if positions:
                for pos in positions:
                    contract = pos.contract
                    symbol = contract.localSymbol if hasattr(contract, 'localSymbol') else contract.symbol
                    qty = pos.position
                    avg_cost = pos.avgCost

                    # Try to calculate current P&L
                    pnl_text = ""
                    try:
                        unrealized_pnl = pos.unrealizedPNL
                        if unrealized_pnl:
                            pnl_pct = (unrealized_pnl / (avg_cost * abs(qty) * 100)) * 100 if avg_cost > 0 else 0
                            pnl_emoji = "📈" if unrealized_pnl > 0 else "📉"
                            pnl_text = f" {pnl_emoji} {unrealized_pnl:+.2f} ({pnl_pct:+.1f}%)"
                    except:
                        pass

                    text += f"• {symbol}: {qty} @ ${avg_cost:.2f}{pnl_text}\n"
            else:
                text += "  No open positions\n"

            text += "\n"

            # Open orders
            text += f"<b>📋 Open Orders ({len(open_orders)}):</b>\n"
            if open_orders:
                for trade in open_orders:
                    contract = trade.contract
                    order = trade.order
                    symbol = contract.localSymbol if hasattr(contract, 'localSymbol') else contract.symbol
                    action = order.action
                    qty = order.totalQuantity
                    price = order.lmtPrice
                    status = trade.orderStatus.status

                    text += f"• {action} {qty} {symbol} @ ${price:.2f} - {status}\n"
            else:
                text += "  No open orders\n"

            text += "\n"

            # Open sessions
            text += f"<b>🔄 Active Sessions ({len(open_sessions)}):</b>\n"
            if open_sessions:
                for session in open_sessions[:5]:  # Show first 5
                    symbol = f"{session.underlying} {session.strike}{session.direction.value[0]}" if session.direction else "?"
                    qty = session.total_quantity
                    text += f"• {symbol} - {qty} contracts\n"
                if len(open_sessions) > 5:
                    text += f"  ... and {len(open_sessions) - 5} more\n"
            else:
                text += "  No active sessions\n"

            # Timestamp
            text += f"\n<i>Updated: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}</i>"

            return text

        except Exception as e:
            return f"❌ Error getting status: {str(e)}"

    async def on_discord_message(
        self, message: str, author: str, message_id: str, timestamp: datetime
    ):
        """
        Callback for Discord messages.

        This is the main processing pipeline.
        """
        session = None
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
                # Log error
                self.logger.log_error(None, "PARSING_ERROR", str(e))
                return

            # Step 2: Correlate to session
            print("\n[2/5] Correlating to trade session...")
            session = self.session_manager.process_event(event)

            # Log Discord message (even if not actionable)
            self.logger.log_discord_message(
                session=session,
                author=author,
                message=message,
                timestamp=timestamp,
                message_id=message_id,
            )

            if not session:
                print("✓ Event processed (non-actionable or ignored)")
                return

            # Log parsed event
            self.logger.log_parsed_event(session=session, event=event)

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

                # Log simulated order
                order_details = {
                    "quantity": quantity,
                    "entry_price": event.entry_price,
                    "stop_loss": event.stop_loss,
                    "targets": event.targets,
                    "mode": "PAPER"
                }
                self.logger.log_order_submitted(
                    session=session,
                    event_type=event.event_type,
                    order_details=order_details,
                )

                # Send Telegram notification for order submission
                if self.notifier:
                    await self.notifier.notify_order_submitted(
                        session=session,
                        event_type=event.event_type,
                        order_details=order_details,
                        paper_mode=True,
                    )

                # Log simulated result
                from ..execution.executor import OrderResult, OrderStatus
                simulated_result = OrderResult(
                    success=True,
                    status=OrderStatus.FILLED,
                    filled_price=event.entry_price,
                    message="Simulated fill (paper mode)"
                )
                self.logger.log_order_result(
                    session=session,
                    event_type=event.event_type,
                    result=simulated_result,
                )

                # Send Telegram notification for order fill
                if self.notifier:
                    await self.notifier.notify_order_filled(
                        session=session,
                        event_type=event.event_type,
                        result=simulated_result,
                        paper_mode=True,
                    )
            else:
                # Log order submission
                order_details = {
                    "quantity": quantity,
                    "entry_price": event.entry_price,
                    "stop_loss": event.stop_loss,
                    "targets": event.targets,
                    "underlying": session.underlying,
                    "strike": session.strike,
                    "expiry": session.expiry,
                    "direction": session.direction.value if session.direction else None
                }
                self.logger.log_order_submitted(
                    session=session,
                    event_type=event.event_type,
                    order_details=order_details,
                )

                # Send Telegram notification for order submission
                if self.notifier:
                    await self.notifier.notify_order_submitted(
                        session=session,
                        event_type=event.event_type,
                        order_details=order_details,
                        paper_mode=False,
                    )

                # Execute the order
                result = await self.executor.execute_event(
                    event=event,
                    session=session,
                    quantity=quantity,
                )

                # Log order result
                self.logger.log_order_result(
                    session=session,
                    event_type=event.event_type,
                    result=result,
                )

                # Send Telegram notification for order fill
                if self.notifier:
                    await self.notifier.notify_order_filled(
                        session=session,
                        event_type=event.event_type,
                        result=result,
                        paper_mode=False,
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

            # Log critical error
            if session:
                self.logger.log_error(session, "CRITICAL_ERROR", str(e))

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
        "telegram": {
            "enabled": os.getenv("TELEGRAM_ENABLED", "false").lower() == "true",
            "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
            "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        },
        "paper_mode": os.getenv("PAPER_MODE", "true").lower() == "true",
    }

    # Create and start orchestrator
    orchestrator = TradingOrchestrator(config)
    await orchestrator.start()


if __name__ == "__main__":
    asyncio.run(main())
