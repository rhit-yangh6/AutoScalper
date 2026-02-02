"""
MNQ Futures Trading Orchestrator

Main orchestrator that coordinates all components for MNQ futures scalping.
TradingView webhook is the sole signal source.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
import pytz

# Fix for ib_insync event loop conflict
import nest_asyncio
nest_asyncio.apply()

from dotenv import load_dotenv

from ..risk_gate import RiskGate
from ..execution import ExecutionEngine
from ib_insync import MarketOrder
from ..tradingview_listener import TradingViewListener
from ..models import Event, EventType
from ..logging import init_logger, DailySnapshotManager, init_balance_logger
from ..notifications import init_notifier


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
        self.balance_logger = init_balance_logger(log_dir=log_dir)
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
        self.risk_gate = RiskGate(config["risk"])

        self.executor = ExecutionEngine(
            host=config["ibkr"]["host"],
            port=config["ibkr"]["port"],
            client_id=config["ibkr"]["client_id"],
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
                f"/plot - Balance history chart\n"
                f"/close - Emergency close\n"
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
            self.notifier.register_command_handler("close", self._handle_close_command)
            self.notifier.register_command_handler("restartgw", self._handle_restartgw_command)
            self.notifier.register_command_handler("plot", self._handle_plot_command)
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

            # Start Friday close task (closes positions before market close)
            print("Starting Friday market close task (1:50 PM PT)...")
            asyncio.create_task(self._friday_close_task())

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

        Position-based logic - checks actual IBKR position, not in-memory state.
        This makes the bot resilient to restarts and disconnections.
        """
        try:
            print(f"\n{'='*60}")
            print(f"SIGNAL: {event.event_type.value} {event.symbol} {event.position_side.value if event.position_side else ''}")
            print(f"{'='*60}")

            # Get current position from IBKR
            if self.dry_run:
                current_side, current_qty, current_avg = "FLAT", 0, 0.0
                print(f"\n[DRY-RUN] Assuming FLAT position")
            else:
                if not self.executor.connected:
                    print("✗ Not connected to IBKR")
                    if self.notifier:
                        await self.notifier.send_message("❌ Signal ignored - IBKR not connected")
                    return

                current_side, current_qty, current_avg = await self.executor.get_mnq_position()
                print(f"\nCurrent position: {current_side} {current_qty} @ ${current_avg:.2f}" if current_qty > 0 else "\nCurrent position: FLAT")

            # Update account balance
            if not self.dry_run and self.executor.connected:
                balance = await self.executor.get_account_balance()
                if balance:
                    self.risk_gate.update_account_balance(balance)

            # Calculate position size
            quantity = self.risk_gate.calculate_position_size(event, None)
            if quantity == 0:
                print("⚠️ Position size = 0 (insufficient margin)")
                return

            # Handle signal based on current position
            if event.event_type == EventType.NEW:
                await self._handle_new_signal(event, current_side, current_qty, current_avg, quantity)

            elif event.event_type == EventType.EXIT or event.event_type == EventType.CLOSE_ALL:
                await self._handle_exit_signal(event, current_side, current_qty, current_avg)

            elif event.event_type == EventType.ADD:
                await self._handle_add_signal(event, current_side, current_qty, quantity)

        except Exception as e:
            import traceback
            print(f"❌ Error processing signal: {e}")
            traceback.print_exc()
            if self.notifier:
                await self.notifier.send_message(f"❌ Error: {str(e)[:200]}")

    async def _handle_new_signal(self, event: Event, current_side: str, current_qty: int, current_avg: float, quantity: int):
        """Handle NEW signal based on current position."""
        signal_side = event.position_side.value if event.position_side else None

        if not signal_side:
            print("✗ NEW signal missing side")
            return

        # FLAT - open new position
        if current_side == "FLAT":
            print(f"\n→ Opening {signal_side} position ({quantity} contracts)")
            await self._execute_entry(event, signal_side, quantity)

        # Same side - already in position
        elif current_side == signal_side:
            print(f"⚠️ Already {current_side} {current_qty} contracts - ignoring NEW signal")
            if self.notifier:
                await self.notifier.send_message(
                    f"⚠️ Signal ignored - already {current_side} {current_qty} contracts"
                )

        # Opposite side - flip position
        else:
            print(f"\n→ FLIP: Closing {current_side} {current_qty} @ ${current_avg:.2f}, then opening {signal_side}")
            # Close current position
            closed = await self._execute_close(current_side, current_qty, current_avg)
            if closed:
                # Open new position
                await self._execute_entry(event, signal_side, quantity)

    async def _handle_exit_signal(self, event: Event, current_side: str, current_qty: int, current_avg: float):
        """Handle EXIT signal - closes any existing position."""
        if current_side == "FLAT":
            print(f"⚠️ EXIT ignored - no open position")
            if self.notifier:
                await self.notifier.send_message(f"⚠️ EXIT ignored - no open position")
            return

        print(f"\n→ Closing {current_side} {current_qty} contracts @ ${current_avg:.2f}")
        await self._execute_close(current_side, current_qty, current_avg)

    async def _handle_add_signal(self, event: Event, current_side: str, current_qty: int, quantity: int):
        """Handle ADD signal based on current position."""
        signal_side = event.position_side.value if event.position_side else None

        if current_side == "FLAT":
            print("⚠️ No position to add to - treating as NEW")
            await self._execute_entry(event, signal_side, quantity)
            return

        if signal_side and current_side != signal_side:
            print(f"⚠️ Cannot ADD {signal_side} to {current_side} position")
            return

        print(f"\n→ Adding {quantity} contracts to {current_side} position")
        await self._execute_add(current_side, quantity)

    async def _execute_entry(self, event: Event, side: str, quantity: int):
        """Execute entry order."""
        if self.dry_run:
            print(f"  [DRY-RUN] Would {('BUY' if side == 'LONG' else 'SELL')} {quantity} MNQ")
            if self.notifier:
                await self.notifier.send_message(
                    f"📝 <b>[DRY-RUN] Entry</b>\n\n"
                    f"MNQ {side} x{quantity}"
                )
            return

        action = "BUY" if side == "LONG" else "SELL"
        contract = self.executor._build_contract("MNQ")
        order = MarketOrder(action, quantity)

        print(f"  Submitting {action} MARKET x{quantity}...")
        trade = self.executor.ib.placeOrder(contract, order)

        filled = await self.executor._wait_for_fill(trade, timeout=30)

        if filled:
            price = trade.orderStatus.avgFillPrice
            print(f"  ✓ Filled @ ${price:.2f}")

            if self.notifier:
                await self.notifier.send_message(
                    f"✅ <b>Entry Filled</b>\n\n"
                    f"MNQ {side}\n"
                    f"Entry: ${price:.2f}\n"
                    f"Qty: {quantity}"
                )
        else:
            print(f"  ✗ Order timeout")
            self.executor.ib.cancelOrder(trade.order)
            if self.notifier:
                await self.notifier.send_message(f"❌ Entry order timed out")

    async def _execute_close(self, current_side: str, current_qty: int, entry_price: float = 0.0) -> bool:
        """Execute close order. Returns True if successful."""
        if self.dry_run:
            print(f"  [DRY-RUN] Would close {current_side} {current_qty}")
            if self.notifier:
                await self.notifier.send_message(
                    f"📝 <b>[DRY-RUN] Exit</b>\n\n"
                    f"MNQ {current_side} x{current_qty}"
                )
            return True

        # To close: SELL if LONG, BUY if SHORT
        action = "SELL" if current_side == "LONG" else "BUY"
        contract = self.executor._build_contract("MNQ")
        order = MarketOrder(action, current_qty)

        print(f"  Submitting {action} MARKET x{current_qty} (close)...")
        trade = self.executor.ib.placeOrder(contract, order)

        filled = await self.executor._wait_for_fill(trade, timeout=30)

        if filled:
            exit_price = trade.orderStatus.avgFillPrice

            # Calculate P&L (MNQ = $2 per point)
            pnl = None
            if entry_price > 0:
                if current_side == "LONG":
                    pnl = (exit_price - entry_price) * current_qty * 2
                else:  # SHORT
                    pnl = (entry_price - exit_price) * current_qty * 2
                pnl_str = f"${pnl:+,.2f}"
                print(f"  ✓ Closed @ ${exit_price:.2f} | P&L: {pnl_str}")
            else:
                print(f"  ✓ Closed @ ${exit_price:.2f}")

            # Log balance after close
            balance = await self.executor.get_account_balance()
            if balance and self.balance_logger:
                self.balance_logger.log_balance(
                    balance=balance,
                    side=current_side,
                    exit_price=exit_price,
                    pnl=pnl
                )

            if self.notifier:
                balance_str = f"\nBalance: ${balance:,.2f}" if balance else ""
                pnl_line = f"\n<b>P&L: {pnl_str}</b>" if pnl is not None else ""
                entry_line = f"\nEntry: ${entry_price:.2f}" if entry_price > 0 else ""
                await self.notifier.send_message(
                    f"📤 <b>Position Closed</b>\n\n"
                    f"MNQ {current_side} x{current_qty}{entry_line}\n"
                    f"Exit: ${exit_price:.2f}{pnl_line}{balance_str}"
                )
            return True
        else:
            print(f"  ✗ Close order timeout")
            self.executor.ib.cancelOrder(trade.order)
            if self.notifier:
                await self.notifier.send_message(f"❌ Close order timed out")
            return False

    async def _execute_add(self, current_side: str, quantity: int):
        """Execute add to position order."""
        if self.dry_run:
            print(f"  [DRY-RUN] Would add {quantity} to {current_side}")
            return

        action = "BUY" if current_side == "LONG" else "SELL"
        contract = self.executor._build_contract("MNQ")
        order = MarketOrder(action, quantity)

        print(f"  Submitting {action} MARKET x{quantity} (add)...")
        trade = self.executor.ib.placeOrder(contract, order)

        filled = await self.executor._wait_for_fill(trade, timeout=30)

        if filled:
            price = trade.orderStatus.avgFillPrice
            print(f"  ✓ Added @ ${price:.2f}")

            if self.notifier:
                await self.notifier.send_message(
                    f"➕ <b>Added to Position</b>\n\n"
                    f"MNQ {current_side}\n"
                    f"Price: ${price:.2f}\n"
                    f"Added: {quantity}"
                )
        else:
            print(f"  ✗ Add order timeout")
            self.executor.ib.cancelOrder(trade.order)

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

    async def _friday_close_task(self):
        """
        Close all positions on Friday before market close.
        MNQ futures close at 4:00 PM CT / 2:00 PM PT on Fridays.
        We close at 1:50 PM PT to give a 10-minute buffer.
        """
        la_tz = pytz.timezone('America/Los_Angeles')
        close_hour = 13  # 1:50 PM PT
        close_minute = 50
        closed_this_week = False

        while self.running:
            try:
                now_la = datetime.now(la_tz)
                weekday = now_la.weekday()  # 0=Monday, 4=Friday
                current_time = now_la.time()

                # Reset flag on Monday
                if weekday == 0 and current_time.hour == 0:
                    closed_this_week = False

                # Only check on Friday (weekday == 4)
                if weekday == 4:
                    # Check if it's 1:50 PM PT (within the minute)
                    if (current_time.hour == close_hour and
                        current_time.minute == close_minute and
                        not closed_this_week):

                        closed_this_week = True
                        print(f"\n{'='*60}")
                        print(f"FRIDAY CLOSE: Closing all positions before market close")
                        print(f"{'='*60}")

                        if self.notifier:
                            await self.notifier.send_message(
                                "📅 <b>Friday Market Close</b>\n\n"
                                "Closing all positions before market close at 2:00 PM PT"
                            )

                        # Get current position
                        side, qty, avg = await self.executor.get_mnq_position()

                        if side != "FLAT" and qty > 0:
                            print(f"Closing {side} {qty} contracts @ ${avg:.2f}...")
                            closed = await self._execute_close(side, qty, avg)
                            if closed:
                                print("✓ Friday close complete")
                            else:
                                print("✗ Friday close failed")
                                if self.notifier:
                                    await self.notifier.send_message("❌ Friday close failed!")
                        else:
                            print("No position to close")
                            if self.notifier:
                                await self.notifier.send_message("✅ No position to close before weekend")

            except Exception as e:
                print(f"Friday close task error: {e}")

            await asyncio.sleep(30)  # Check every 30 seconds

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

            # Account & Position
            if not self.dry_run and self.executor.connected:
                balance = await self.executor.get_account_balance()
                if balance:
                    text += f"<b>💰 Balance:</b> ${balance:,.2f}\n\n"

                # Get MNQ position
                side, qty, avg_price = await self.executor.get_mnq_position()
                text += f"<b>📈 Position:</b>\n"
                if side == "FLAT":
                    text += "  No open position\n"
                else:
                    text += f"  MNQ {side} x{qty} @ ${avg_price:.2f}\n"
            else:
                text += "<b>📈 Position:</b>\n"
                text += "  Not connected to IBKR\n"

            # Stats
            text += f"\n<b>📊 Today:</b>\n"
            text += f"• P&L: ${self.risk_gate.daily_pnl:+,.2f}\n"
            text += f"• Trades: {len(self.risk_gate.trades_today)}\n"

            # Connection status
            text += f"\n<b>🔌 Connection:</b>\n"
            text += f"• IBKR: {'✅ Connected' if self.executor.connected else '❌ Disconnected'}\n"

            text += f"\n<i>{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}</i>"
            return text

        except Exception as e:
            return f"❌ Error: {str(e)}"

    async def _handle_close_command(self, cmd: dict) -> str:
        """Handle /close command - emergency close position."""
        try:
            if self.dry_run:
                return "❌ Cannot close positions in DRY-RUN mode"

            if not self.executor.connected:
                return "❌ Not connected to IBKR"

            # Get current MNQ position
            side, qty, avg_price = await self.executor.get_mnq_position()

            if side == "FLAT" or qty == 0:
                return "✅ No position to close"

            # Use the working _execute_close method (which logs balance and calculates P&L)
            text = f"<b>🚨 Emergency Close</b>\n\nClosing {side} x{qty} @ ${avg_price:.2f}...\n\n"

            closed = await self._execute_close(side, qty, avg_price)

            if closed:
                # Get and display final balance
                balance = await self.executor.get_account_balance()
                balance_str = f"\nBalance: ${balance:,.2f}" if balance else ""
                text += f"✅ Position closed successfully{balance_str}"
            else:
                text += "❌ Failed to close position"

            return text

        except Exception as e:
            import traceback
            traceback.print_exc()
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

    async def _handle_plot_command(self, cmd: dict) -> str:
        """Handle /plot command - generate balance history chart."""
        try:
            if not self.balance_logger:
                return "❌ Balance logger not initialized"

            # Generate plot
            plot_data = self.balance_logger.generate_plot()

            if not plot_data:
                return "❌ Not enough data to generate plot (need at least 2 data points)"

            # Send image via Telegram
            if self.notifier:
                sent = await self.notifier.send_photo(
                    photo=plot_data,
                    caption="📈 Balance History"
                )
                if sent:
                    return ""  # Empty string means don't send text message
                else:
                    return "❌ Failed to send plot image"

            return "❌ Notifier not available"

        except Exception as e:
            return f"❌ Error generating plot: {str(e)}"


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
