"""
MNQ Futures Trading Orchestrator

Main orchestrator that coordinates all components for MNQ futures scalping.
TradingView webhook is the sole signal source.
"""

import asyncio
from datetime import datetime, time, timezone
from typing import Optional

# Fix for ib_insync event loop conflict
import nest_asyncio
nest_asyncio.apply()

from dotenv import load_dotenv

from ..risk_gate import RiskGate, RiskDecision
from ..execution import ExecutionEngine
from ..execution.executor import OrderResult, OrderStatus
from ..tradingview_listener import TradingViewListener
from .session_manager import SessionManager
from ..models import Event, EventType, SessionState, TradeSession, PositionSide
from ..logging import init_logger, get_logger, DailySnapshotManager
from ..notifications import init_notifier, get_notifier


class TradingOrchestrator:
    """
    Main orchestrator for MNQ futures trading.

    Flow:
    1. TradingView webhook received
    2. Parse structured JSON to Event (no LLM)
    3. Session manager correlates Event to TradeSession
    4. Risk gate validates
    5. Execution engine executes (if approved)
    """

    def __init__(self, config: dict):
        self.config = config

        print("Initializing MNQ Futures Trading Orchestrator...")

        # Initialize logger
        log_dir = config.get("log_dir", "logs")
        self.logger = init_logger(base_dir=log_dir)
        self.snapshot_manager = DailySnapshotManager(base_dir=log_dir)
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

        # Initialize components
        self.session_manager = SessionManager()
        self.risk_gate = RiskGate(config["risk"])

        self.executor = ExecutionEngine(
            host=config["ibkr"]["host"],
            port=config["ibkr"]["port"],
            client_id=config["ibkr"]["client_id"],
            session_manager=self.session_manager,
            config=config,
            notifier=self.notifier,
        )

        # Initialize TradingView webhook listener
        self.tradingview_listener = TradingViewListener(
            port=config["tradingview"]["webhook_port"],
            webhook_secret=config["tradingview"]["webhook_secret"],
            on_signal=self.on_tradingview_signal,
        )
        print(f"✓ Signal source: TradingView webhook")

        # State
        self.running = False
        self.dry_run = config.get("dry_run", True)
        self.start_time = None

        print(f"Orchestrator initialized (dry_run={self.dry_run})")

    async def start(self):
        """Start the orchestrator."""
        print("\n" + "=" * 60)
        print("STARTING MNQ FUTURES SCALPER")
        print("=" * 60)
        print(f"Mode: {'DRY-RUN (No IBKR)' if self.dry_run else 'LIVE TRADING'}")
        num_contracts = self.config['risk'].get('num_contracts', 1)
        if num_contracts == 0:
            print(f"Contracts: AUTO (based on balance)")
        else:
            print(f"Contracts: {num_contracts}")
        print("=" * 60 + "\n")

        self.running = True
        self.start_time = datetime.now(timezone.utc)

        # Send Telegram startup notification immediately
        if self.notifier:
            mode = "DRY-RUN" if self.dry_run else "LIVE"
            num_contracts = self.config['risk'].get('num_contracts', 1)
            contracts_str = "AUTO" if num_contracts == 0 else str(num_contracts)
            startup_msg = (
                f"🚀 <b>AutoScalper Started</b>\n\n"
                f"Mode: {mode}\n"
                f"Contracts: {contracts_str}\n"
                f"Webhook Port: {self.config['tradingview']['webhook_port']}\n\n"
                f"<b>Commands:</b>\n"
                f"/status - Check positions\n"
                f"/closeall - Emergency close\n"
                f"/restartgw - Restart IB Gateway"
            )
            sent = await self.notifier.send_message(startup_msg)
            if sent:
                print("✓ Startup notification sent to Telegram")
            else:
                print("✗ Failed to send Telegram notification - check bot token and chat ID")

            # Start Telegram command listener early (works even without IBKR)
            print("Starting Telegram command handler...")
            self.notifier.register_command_handler("status", self._handle_status_command)
            self.notifier.register_command_handler("closeall", self._handle_closeall_command)
            self.notifier.register_command_handler("restartgw", self._handle_restartgw_command)
            asyncio.create_task(self._telegram_polling_task())

        # Connect to IBKR
        if not self.dry_run:
            print("Connecting to IBKR...")
            max_retries = 10
            retry_delay = 5

            for attempt in range(1, max_retries + 1):
                print(f"Connection attempt {attempt}/{max_retries}...")
                connected = await self.executor.connect()

                if connected:
                    break

                if attempt < max_retries:
                    print(f"Connection failed. Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 60)
                else:
                    print("ERROR: Failed to connect to IBKR. Exiting.")
                    return

            # Fetch live margin requirement from IBKR
            await self._fetch_margin_requirement()

            # Send IBKR connected notification
            await self._send_ibkr_connected_notification()
        else:
            print("Skipping IBKR connection (dry-run mode)")

        # Start TradingView webhook
        print("Starting TradingView webhook server...")
        await self.tradingview_listener.start()

        # Start connection monitor
        if not self.dry_run:
            print("Starting connection monitor...")
            asyncio.create_task(self._connection_monitor_task())

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

        if self.tradingview_listener:
            await self.tradingview_listener.stop()

        if not self.dry_run:
            await self.executor.disconnect()

        print("Flushing logs...")
        self.logger.flush_all()

        print("Orchestrator stopped.")

    async def on_tradingview_signal(self, event: Event):
        """
        Callback for TradingView webhook signals.

        This is the main processing pipeline.
        """
        session = None
        try:
            print(f"\n{'='*60}")
            print(f"PROCESSING SIGNAL: {event.event_type.value}")
            print(f"{'='*60}")

            # Step 0: Check for position flip (opposite side needs to be closed first)
            if event.event_type == EventType.NEW:
                opposite_session = self.session_manager.check_for_flip(event)
                if opposite_session and opposite_session.state == SessionState.OPEN:
                    print("\n[FLIP DETECTED] Closing opposite position first...")
                    print(f"  Closing: {opposite_session.symbol} {opposite_session.position_side.value}")
                    await self._close_session_for_flip(opposite_session)

            # Step 1: Correlate to session
            print("\n[1/4] Correlating to trade session...")
            try:
                session = self.session_manager.process_event(event)
            except ValueError as e:
                print(f"✗ Session error: {e}")
                if self.notifier:
                    await self.notifier.send_message(f"⚠️ Signal rejected: {e}")
                return

            if not session:
                print("✓ Event processed (non-actionable)")
                return

            print(f"✓ Session {session.session_id[:8]}...")
            print(f"  {session.symbol} {session.position_side.value if session.position_side else '?'}")
            print(f"  State: {session.state}")

            # Step 2: Risk validation
            print("\n[2/4] Validating with risk gate...")

            unrealized_pnl = 0.0
            if not self.dry_run and self.executor.connected:
                balance = await self.executor.get_account_balance()
                if balance:
                    self.risk_gate.update_account_balance(balance)

            risk_result = self.risk_gate.validate(
                event=event,
                session=session,
                unrealized_pnl=unrealized_pnl,
            )

            status = "✓" if risk_result.decision == RiskDecision.APPROVE else "✗"
            print(f"{status} {risk_result.decision}: {risk_result.reason}")

            if risk_result.decision == RiskDecision.REJECT:
                if event.event_type == EventType.NEW:
                    session.state = SessionState.CANCELLED
                    session.closed_at = datetime.now(timezone.utc)

                if self.notifier:
                    await self.notifier.send_message(
                        f"⚠️ <b>Trade Rejected</b>\n\n"
                        f"{event.symbol} {event.position_side.value if event.position_side else ''}\n"
                        f"Reason: {risk_result.reason}"
                    )
                return

            # Step 3: Calculate position size
            print("\n[3/4] Calculating position size...")
            quantity = self.risk_gate.calculate_position_size(event, session)
            print(f"✓ Position size: {quantity} contracts")

            if quantity == 0:
                print("⚠️ Position size = 0 (limit reached)")
                return

            # Step 4: Execute
            print("\n[4/4] Executing order...")

            if self.dry_run:
                print("  [DRY-RUN] Order would be executed")
                result = OrderResult(
                    success=True,
                    status=OrderStatus.FILLED,
                    message="[DRY-RUN] Simulated fill"
                )
            else:
                result = await self.executor.execute_event(
                    event=event,
                    session=session,
                    quantity=quantity,
                )

            # Log result
            if result.success:
                print(f"✓ {result.message}")
                self.logger.log_execution(session, event, result)

                # Send Telegram notification
                if self.notifier:
                    if event.event_type == EventType.NEW:
                        side = event.position_side.value if event.position_side else "?"
                        await self.notifier.send_message(
                            f"✅ <b>Entry Filled</b>\n\n"
                            f"{event.symbol} {side}\n"
                            f"Entry: ${result.filled_price:.2f}\n"
                            f"Qty: {quantity}"
                        )
                    elif event.event_type in [EventType.EXIT, EventType.CLOSE_ALL]:
                        side = session.position_side.value if session.position_side else "?"
                        pnl = session.realized_pnl
                        await self.notifier.send_message(
                            f"📤 <b>Exit Filled</b>\n\n"
                            f"{session.symbol} {side}\n"
                            f"Exit: ${result.filled_price:.2f}\n"
                            f"P&L: ${pnl:+,.2f}"
                        )
                        # Record trade result for risk tracking
                        self.risk_gate.record_trade_result(pnl)
            else:
                print(f"✗ {result.message}")
                self.logger.log_error(session, "EXECUTION_ERROR", result.message)

                if self.notifier:
                    await self.notifier.send_message(
                        f"❌ <b>Execution Failed</b>\n\n"
                        f"{event.symbol}\n"
                        f"Error: {result.message}"
                    )

        except Exception as e:
            import traceback
            print(f"❌ Error processing signal: {e}")
            traceback.print_exc()

            if self.notifier:
                await self.notifier.send_message(f"❌ Error: {str(e)[:200]}")

    async def _close_session_for_flip(self, session: TradeSession):
        """
        Close an existing position before flipping to opposite side.

        This is called when a NEW signal comes in for the opposite side
        of an existing open position.
        """
        try:
            side = session.position_side.value if session.position_side else "?"
            print(f"  Flipping from {session.symbol} {side}...")

            # Create synthetic EXIT event
            exit_event = Event(
                event_type=EventType.EXIT,
                symbol=session.symbol,
                position_side=session.position_side,
                timestamp=datetime.now(timezone.utc),
                author=session.author,
                message_id=f"flip_exit_{datetime.now(timezone.utc).timestamp()}",
                raw_message="Auto-generated EXIT for position flip",
            )

            # Execute the exit
            if self.dry_run:
                print(f"  [DRY-RUN] Would close {session.total_quantity} contracts")
                # Update session state for dry run
                session.state = SessionState.CLOSED
                session.closed_at = datetime.now(timezone.utc)
                session.exit_reason = "FLIP_EXIT"
            else:
                result = await self.executor.execute_event(
                    event=exit_event,
                    session=session,
                    quantity=session.total_quantity,
                )

                if result.success:
                    pnl = session.realized_pnl
                    print(f"  ✓ Flip exit filled @ ${result.filled_price:.2f} | P&L: ${pnl:+,.2f}")

                    # Record trade result
                    self.risk_gate.record_trade_result(pnl)

                    # Log the exit
                    self.logger.log_execution(session, exit_event, result)

                    # Notify
                    if self.notifier:
                        await self.notifier.send_message(
                            f"🔄 <b>Position Flipped</b>\n\n"
                            f"Closed: {session.symbol} {side}\n"
                            f"Exit: ${result.filled_price:.2f}\n"
                            f"P&L: ${pnl:+,.2f}\n\n"
                            f"<i>Opening opposite position...</i>"
                        )
                else:
                    print(f"  ✗ Flip exit failed: {result.message}")
                    if self.notifier:
                        await self.notifier.send_message(
                            f"❌ <b>Flip Exit Failed</b>\n\n"
                            f"{session.symbol} {side}\n"
                            f"Error: {result.message}"
                        )
                    raise Exception(f"Failed to close position for flip: {result.message}")

        except Exception as e:
            print(f"  ✗ Error closing position for flip: {e}")
            raise

    async def _fetch_margin_requirement(self):
        """Fetch live margin requirement from IBKR and update risk gate."""
        try:
            print("Fetching margin requirement from IBKR...")
            margin = await self.executor.get_margin_requirement("MNQ")

            if margin and margin > 0:
                self.risk_gate.update_margin_requirement(margin)
            else:
                fallback = self.config["risk"].get("margin_per_contract", 2000)
                print(f"Could not fetch margin, using config value: ${fallback:,.2f}")

        except Exception as e:
            print(f"Error fetching margin: {e}")
            fallback = self.config["risk"].get("margin_per_contract", 2000)
            print(f"Using fallback margin: ${fallback:,.2f}")

    async def _send_ibkr_connected_notification(self):
        """Send Telegram notification when IBKR is connected with account info."""
        if not self.notifier:
            return

        try:
            # Get account balance
            balance = await self.executor.get_account_balance()
            balance_str = f"${balance:,.2f}" if balance else "N/A"

            # Get margin info
            margin = self.config["risk"].get("margin_per_contract", 2000)
            margin_buffer = self.config["risk"].get("margin_buffer", 0.80)

            # Calculate max contracts
            num_contracts = self.config["risk"].get("num_contracts", 1)
            if num_contracts == 0 and balance and margin > 0:
                usable = balance * margin_buffer
                max_contracts = int(usable / margin)
                contracts_str = f"AUTO ({max_contracts} max)"
            else:
                contracts_str = str(num_contracts)

            # Get front-month contract info
            contract_name = "MNQ"
            if hasattr(self.executor, '_front_month_contract') and self.executor._front_month_contract:
                contract_name = self.executor._front_month_contract.localSymbol

            msg = (
                f"✅ <b>IBKR Connected</b>\n\n"
                f"<b>Account:</b>\n"
                f"• Balance: {balance_str}\n"
                f"• Margin/Contract: ${margin:,.2f}\n"
                f"• Safety Buffer: {margin_buffer:.0%}\n\n"
                f"<b>Trading:</b>\n"
                f"• Contract: {contract_name}\n"
                f"• Contracts: {contracts_str}\n\n"
                f"<i>Ready to receive signals</i>"
            )

            await self.notifier.send_message(msg)
            print("✓ IBKR connected notification sent to Telegram")

        except Exception as e:
            print(f"Error sending IBKR connected notification: {e}")

    async def _connection_monitor_task(self):
        """Monitor IBKR connection and reconnect if needed."""
        disconnect_notified = False

        while self.running:
            await asyncio.sleep(30)

            if not self.executor.connected:
                # Send disconnect notification only once
                if not disconnect_notified and self.notifier:
                    disconnect_notified = True
                    await self.notifier.send_message(
                        "⚠️ <b>IBKR Disconnected</b>\n\n"
                        "Connection lost. Attempting auto-reconnect..."
                    )

                print("⚠️ IBKR disconnected. Attempting reconnect...")
                success = await self.executor.reconnect()

                # Send reconnect notification on success
                if success and disconnect_notified:
                    disconnect_notified = False
                    duration_msg = ""
                    if self.executor._disconnected_at:
                        from datetime import datetime, timezone
                        duration = datetime.now(timezone.utc) - self.executor._disconnected_at
                        minutes = int(duration.total_seconds() / 60)
                        if minutes > 0:
                            duration_msg = f"\nDowntime: {minutes} minute(s)"

                    if self.notifier:
                        await self.notifier.send_message(
                            f"✅ <b>IBKR Reconnected</b>\n\n"
                            f"Connection restored.{duration_msg}"
                        )
            else:
                # Reset notification flag when connected
                disconnect_notified = False

    async def _telegram_polling_task(self):
        """Poll for Telegram commands."""
        while self.running:
            try:
                await self.notifier.process_commands()
                await asyncio.sleep(5)
            except Exception as e:
                print(f"Telegram polling error: {e}")
                await asyncio.sleep(5)

    async def _handle_status_command(self, cmd: dict) -> str:
        """Handle /status command."""
        try:
            mode = "📝 DRY-RUN" if self.dry_run else "🔴 LIVE"
            text = f"<b>📊 {mode} STATUS</b>\n\n"

            # Account
            if not self.dry_run and self.executor.connected:
                balance = await self.executor.get_account_balance()
                if balance:
                    text += f"<b>💰 Balance:</b> ${balance:,.2f}\n\n"

            # Positions
            positions = []
            if not self.dry_run and self.executor.connected:
                positions = await self.executor.get_positions()

            text += f"<b>🔓 Positions ({len(positions)}):</b>\n"
            if positions:
                for pos in positions:
                    symbol = pos.contract.localSymbol if hasattr(pos.contract, 'localSymbol') else pos.contract.symbol
                    side = "LONG" if pos.position > 0 else "SHORT"
                    text += f"• {symbol}: {abs(int(pos.position))} {side} @ ${pos.avgCost:.2f}\n"
            else:
                text += "  No open positions\n"

            # Sessions
            open_sessions = [s for s in self.session_manager.sessions.values() if s.state == SessionState.OPEN]
            text += f"\n<b>📊 Sessions ({len(open_sessions)}):</b>\n"
            if open_sessions:
                for s in open_sessions[:5]:
                    side = s.position_side.value if s.position_side else "?"
                    text += f"• {s.symbol} {side}: {s.total_quantity} contracts\n"
            else:
                text += "  No active sessions\n"

            # Stats
            text += f"\n<b>📈 Today:</b>\n"
            text += f"• P&L: ${self.risk_gate.daily_pnl:+,.2f}\n"
            text += f"• Trades: {len(self.risk_gate.trades_today)}\n"

            text += f"\n<i>{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}</i>"
            return text

        except Exception as e:
            return f"❌ Error: {str(e)}"

    async def _handle_closeall_command(self, cmd: dict) -> str:
        """Handle /closeall command - emergency close all positions."""
        try:
            if self.dry_run:
                return "❌ Cannot close positions in DRY-RUN mode"

            if not self.executor.connected:
                return "❌ Not connected to IBKR"

            results = await self.executor.close_all_positions()

            if not results:
                return "✅ No positions to close"

            text = "<b>🚨 Emergency Close All</b>\n\n"
            for r in results:
                status = "✅" if r.success else "❌"
                text += f"{status} {r.message}\n"

            return text

        except Exception as e:
            return f"❌ Error: {str(e)}"

    async def _handle_restartgw_command(self, cmd: dict) -> str:
        """Handle /restartgw command - restart IB Gateway Docker container."""
        import subprocess

        try:
            # Mark as disconnected since gateway is restarting
            self.executor.connected = False

            # Run docker compose restart
            result = subprocess.run(
                ["docker", "compose", "restart", "ib-gateway"],
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout
            )

            if result.returncode == 0:
                response = "✅ <b>IB Gateway Restarted</b>\n\n"
                response += "Container restarted successfully.\n"
                response += "<i>Auto-reconnect will attempt shortly.</i>"
                return response
            else:
                response = "❌ <b>Restart Failed</b>\n\n"
                response += f"Error: {result.stderr[:200] if result.stderr else 'Unknown error'}"
                return response

        except subprocess.TimeoutExpired:
            return "❌ <b>Restart Timeout</b>\n\nCommand timed out after 2 minutes."
        except FileNotFoundError:
            return "❌ <b>Docker Not Found</b>\n\nDocker or docker compose is not installed."
        except Exception as e:
            return f"❌ Error: {str(e)}"


def load_config() -> dict:
    """Load configuration from .env file."""
    import os

    # Load .env file
    load_dotenv()

    def env(key: str, default=None, cast=str):
        """Get env var with optional type casting."""
        value = os.getenv(key, default)
        if value is None:
            return None
        if cast == bool:
            return str(value).lower() in ("true", "1", "yes")
        return cast(value)

    config = {
        "dry_run": env("DRY_RUN", "true", bool),
        "log_dir": env("LOG_DIR", "logs"),

        "ibkr": {
            "host": env("IBKR_HOST", "127.0.0.1"),
            "port": env("IBKR_PORT", 4002, int),
            "client_id": env("IBKR_CLIENT_ID", 1, int),
        },

        "tradingview": {
            "webhook_port": env("TRADINGVIEW_WEBHOOK_PORT", 8080, int),
            "webhook_secret": env("TRADINGVIEW_WEBHOOK_SECRET", ""),
        },

        "risk": {
            "account_balance": env("ACCOUNT_BALANCE", 10000, float),
            "num_contracts": env("NUM_CONTRACTS", 1, int),
            "margin_per_contract": env("MARGIN_PER_CONTRACT", 2000, float),
            "margin_buffer": env("MARGIN_BUFFER", 0.80, float),
        },

        "telegram": {
            "enabled": env("TELEGRAM_ENABLED", "false", bool),
            "bot_token": env("TELEGRAM_BOT_TOKEN", ""),
            "chat_id": env("TELEGRAM_CHAT_ID", ""),
        },
    }

    return config


if __name__ == "__main__":
    try:
        print("Loading configuration from .env...")
        config = load_config()

        print("Creating orchestrator...")
        orchestrator = TradingOrchestrator(config)

        print("Starting...")
        asyncio.run(orchestrator.start())

    except KeyboardInterrupt:
        print("\nShutdown requested.")
    except Exception as e:
        import traceback
        print(f"FATAL ERROR: {e}")
        traceback.print_exc()
        import sys
        sys.exit(1)
