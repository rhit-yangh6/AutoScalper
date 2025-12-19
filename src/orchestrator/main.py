import asyncio
import os
import platform
from datetime import datetime, time, timezone
from typing import Optional

from dotenv import load_dotenv

from ..llm_parser import LLMParser
from ..risk_gate import RiskGate, RiskDecision
from ..execution import ExecutionEngine
from ..execution.executor import OrderResult
from ..discord_listener import DiscordListener
from .session_manager import SessionManager
from ..models import Event, EventType, SessionState, TradeSession
from ..logging import init_logger, get_logger, DailySnapshotManager
from ..notifications import init_notifier, get_notifier

# Optional psutil for system monitoring
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


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

        self.parser = LLMParser(
            api_key=config["anthropic_api_key"],
            model=config.get("llm_model", "claude-opus-4-5-20251101"),
        )

        self.session_manager = SessionManager()

        self.risk_gate = RiskGate(config["risk"])

        # Determine order strategy based on IBKR port and config
        # Gateway ports: 4001 (live), 4002 (paper)
        # TWS ports: 7497 (live), 7496 (paper)
        # Paper accounts always use market orders (delayed data)
        # Live accounts can use market OR limit orders (configurable)
        ibkr_port = config["ibkr"]["port"]
        paper_ports = [4002, 7496]  # Gateway paper, TWS paper
        force_market = config["ibkr"].get("force_market_orders", False)

        # Use market orders if: paper account OR force_market_orders=true
        use_market_orders = (ibkr_port in paper_ports) or force_market

        self.executor = ExecutionEngine(
            host=config["ibkr"]["host"],
            port=ibkr_port,
            client_id=config["ibkr"]["client_id"],
            session_manager=self.session_manager,
            use_market_orders=use_market_orders,
            config=config,
        )

        # Register bracket fill callback
        self.executor.on_bracket_filled = self._on_bracket_filled

        # Register connection callbacks
        self.executor.on_disconnected = self._on_ibkr_disconnected
        self.executor.on_reconnected = self._on_ibkr_reconnected

        self.discord_listener = DiscordListener(
            token=config["discord"]["user_token"],
            channel_ids=config["discord"]["channel_ids"],
            monitored_users=config["discord"].get("monitored_users"),
            message_callback=self.on_discord_message,
        )

        # State
        self.running = False
        self.dry_run = config.get("dry_run", True)
        self.start_time = None  # Will be set when bot starts

        print(
            f"Orchestrator initialized (dry_run={self.dry_run})"
        )

    def _categorize_orders(self, open_orders, open_sessions):
        """Categorize orders into entry, stop, and target."""
        bracket_order_ids = set()
        for session in open_sessions:
            if session.stop_order_id:
                bracket_order_ids.add(session.stop_order_id)
            if session.target_order_ids:
                bracket_order_ids.update(session.target_order_ids)

        entry_orders, stop_orders, target_orders = [], [], []

        for trade in open_orders:
            order_id = trade.order.orderId
            if order_id not in bracket_order_ids:
                entry_orders.append(trade)
                continue

            # Find bracket type
            for session in open_sessions:
                if session.stop_order_id == order_id:
                    stop_orders.append(trade)
                    break
                elif session.target_order_ids and order_id in session.target_order_ids:
                    target_orders.append(trade)
                    break

        return entry_orders, stop_orders, target_orders

    def _get_resource_emoji(self, percent: float, warn_threshold: float, critical_threshold: float) -> str:
        """Get emoji based on resource usage percentage."""
        if percent < warn_threshold:
            return "✅"
        elif percent < critical_threshold:
            return "⚠️"
        return "🔴"

    async def start(self):
        """Start the orchestrator."""
        print("\n" + "=" * 60)
        print("STARTING AUTOSCALPER")
        print("=" * 60)
        print(f"Mode: {'DRY-RUN (No IBKR)' if self.dry_run else 'LIVE TRADING'}")
        print(f"Risk per trade: {self.config['risk']['risk_per_trade_percent']}%")
        print(f"Daily max loss: {self.config['risk']['daily_max_loss_percent']}%")
        print(f"Max contracts: {self.config['risk']['max_contracts']}")
        print("=" * 60 + "\n")

        self.running = True
        self.start_time = datetime.now(timezone.utc)

        # Connect to IBKR (only if not in paper mode)
        if not self.dry_run:
            print("Connecting to IBKR...")

            # Retry connection up to 10 times with exponential backoff
            max_retries = 10
            retry_delay = 5  # Start with 5 seconds

            for attempt in range(1, max_retries + 1):
                print(f"Connection attempt {attempt}/{max_retries}...")
                connected = await self.executor.connect()

                if connected:
                    break

                if attempt < max_retries:
                    print(f"Connection failed. Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 60)  # Max 60 seconds
                else:
                    print("ERROR: Failed to connect to IBKR after all retries. Exiting.")
                    return
        else:
            print("Skipping IBKR connection (paper mode - no orders will be sent)")

        # Start Discord listener
        print("Starting Discord listener...")
        asyncio.create_task(self.discord_listener.start())

        # Start daily summary and snapshot tasks if Telegram enabled
        if self.notifier:
            print("Starting daily summary scheduler...")
            asyncio.create_task(self._daily_summary_task())
            print("Starting daily snapshot scheduler...")
            asyncio.create_task(self._daily_snapshot_task())

            # Register and start Telegram command polling
            print("Starting Telegram command handler...")
            self.notifier.register_command_handler("status", self._handle_status_command)
            self.notifier.register_command_handler("server", self._handle_server_command)
            self.notifier.register_command_handler("closeall", self._handle_closeall_command)
            asyncio.create_task(self._telegram_command_polling_task())

        # Start connection monitoring (if not in dry-run mode)
        if not self.dry_run:
            print("Starting IBKR connection monitor...")
            asyncio.create_task(self._connection_monitor_task())

            print("Starting position reconciliation...")
            asyncio.create_task(self._position_reconciliation_task())

            print("Starting EOD auto-close scheduler...")
            asyncio.create_task(self._eod_auto_close_task())

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
        if not self.dry_run:
            await self.executor.disconnect()

        # Flush all logs
        print("Flushing logs...")
        self.logger.flush_all()

        print("Orchestrator stopped.")

    async def _daily_snapshot_task(self):
        """
        Background task that takes snapshot at trading_hours_start.

        Uses TRADING_HOURS_START from config (default: 13:30 UTC = 9:30 AM ET)
        """
        snapshot_time_str = self.config["risk"]["trading_hours_start"]
        try:
            hour, minute = map(int, snapshot_time_str.split(":"))
            snapshot_time = time(hour=hour, minute=minute)
        except (ValueError, TypeError, AttributeError) as e:
            # Default to 9:30 AM ET (13:30 UTC)
            snapshot_time = time(hour=13, minute=30)
            print(f"Invalid snapshot time format: {e}")

        print(f"Daily snapshot will be taken at {snapshot_time_str} UTC (trading hours start)")

        while self.running:
            now = datetime.now(timezone.utc)
            target_time = datetime.combine(now.date(), snapshot_time, tzinfo=timezone.utc)

            # If target time already passed today, check if snapshot exists
            if now > target_time:
                # Try to take snapshot now (will skip if already exists)
                try:
                    snapshot = await self.snapshot_manager.take_snapshot(
                        executor=self.executor,
                        dry_run=self.dry_run,
                        account_balance_config=self.config["risk"]["account_balance"],
                        trading_hours_start=snapshot_time_str
                    )
                    if snapshot:
                        print(f"✓ Daily snapshot taken: ${snapshot['account_balance']:,.2f}")
                except Exception as e:
                    print(f"✗ Failed to take snapshot: {e}")

                # Schedule for tomorrow
                from datetime import timedelta
                target_time += timedelta(days=1)

            # Calculate seconds until target time
            seconds_until_snapshot = (target_time - now).total_seconds()

            # Wait until snapshot time
            await asyncio.sleep(seconds_until_snapshot)

            # Take snapshot
            if self.running:
                try:
                    print(f"\nTaking daily snapshot at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}...")

                    snapshot = await self.snapshot_manager.take_snapshot(
                        executor=self.executor,
                        dry_run=self.dry_run,
                        account_balance_config=self.config["risk"]["account_balance"],
                        trading_hours_start=snapshot_time_str
                    )

                    if snapshot:
                        print(f"✓ Snapshot saved: ${snapshot['account_balance']:,.2f}")

                except Exception as e:
                    print(f"✗ Failed to take snapshot: {e}")

            # Wait a bit to avoid taking multiple snapshots
            await asyncio.sleep(60)

    async def _daily_summary_task(self):
        """
        Background task that sends daily summary after trading hours end.

        Uses TRADING_HOURS_END from config (default: 20:00 UTC = 4:00 PM ET)
        """
        summary_time_str = self.config["risk"]["trading_hours_end"]
        try:
            hour, minute = map(int, summary_time_str.split(":"))
            summary_time = time(hour=hour, minute=minute)
        except (ValueError, TypeError, AttributeError) as e:
            # Default to 8 PM UTC (4 PM ET)
            summary_time = time(hour=20, minute=0)
            print(f"Invalid summary time format: {e}")

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

                    # Get today's date
                    today = datetime.now(timezone.utc).date().isoformat()

                    # Get snapshot for today
                    snapshot = self.snapshot_manager.get_snapshot_for_date(today)

                    # Get current account balance if connected to IBKR
                    account_balance = None
                    if self.executor.connected:
                        # Get balance for both paper and live modes
                        account_balance = await self.executor.get_account_balance()

                    # Send summary using snapshot + logs
                    await self.notifier.send_daily_summary(
                        date_str=today,
                        snapshot=snapshot,
                        account_balance=account_balance,
                        log_dir=self.config.get("log_dir", "logs")
                    )

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
        print("Telegram command polling active")
        print("  Available commands: /status, /server, /closeall")

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
            mode = "📝 DRY-RUN" if self.dry_run else "🔴 LIVE"

            # Get account balance and cash details
            account_balance = None
            cash_details = None
            if not self.dry_run and self.executor.connected:
                account_balance = await self.executor.get_account_balance()
                cash_details = self.executor.get_cash_details()

            # Get positions
            positions = []
            if not self.dry_run and self.executor.connected:
                positions = await self.executor.get_positions()

            # Get open orders
            open_orders = []
            if not self.dry_run and self.executor.connected:
                open_orders = await self.executor.get_open_orders()

            # Get active sessions
            open_sessions = [s for s in self.session_manager.sessions.values() if s.state == SessionState.OPEN]

            # Build response
            text = f"<b>📊 {mode} STATUS</b>\n\n"

            # Account balance with cash details
            if cash_details:
                text += f"<b>💰 Account Value:</b> ${cash_details.get('net_liquidation', 0):,.2f}\n"

                # Show available cash (critical for Cash accounts)
                available = cash_details.get('available_funds')
                settled = cash_details.get('settled_cash')

                if available is not None:
                    text += f"<b>💵 Available Cash:</b> ${available:,.2f}"
                    if settled is not None and settled != available:
                        text += f" (${settled:,.2f} settled)"
                    text += "\n"
                elif account_balance:
                    text += f"<b>💵 Cash:</b> ${account_balance:,.2f}\n"

                text += "\n"
            elif account_balance:
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

                    # Get current market price for live P&L
                    current_price = None
                    pnl_text = ""
                    try:
                        # Set exchange for market data request (required by IBKR)
                        contract.exchange = "SMART"

                        # Request market data snapshot
                        ticker = self.executor.ib.reqMktData(contract, snapshot=True)
                        await asyncio.sleep(0.5)  # Wait for market data

                        import math
                        # Try to get current price from market data
                        if ticker.last and not math.isnan(ticker.last):
                            current_price = ticker.last
                        elif ticker.bid and ticker.ask and not math.isnan(ticker.bid) and not math.isnan(ticker.ask):
                            current_price = (ticker.bid + ticker.ask) / 2  # Use midpoint
                        elif ticker.close and not math.isnan(ticker.close):
                            current_price = ticker.close

                        # Cancel market data subscription
                        self.executor.ib.cancelMktData(contract)

                        # Calculate P&L if we have current price
                        if current_price and avg_cost > 0 and abs(qty) > 0:
                            # For options: current_price is premium, avg_cost is already in dollars
                            # Convert premium to dollar value first
                            current_value = current_price * 100  # Premium to dollar value
                            unrealized_pnl = (current_value - avg_cost) * qty
                            pnl_pct = ((current_value - avg_cost) / avg_cost) * 100
                            pnl_emoji = "📈" if unrealized_pnl > 0 else "📉"
                            pnl_text = f" → ${current_price:.2f} | {pnl_emoji} ${unrealized_pnl:+.2f} ({pnl_pct:+.1f}%)"

                    except Exception as e:
                        # Fallback to IBKR's unrealized P&L if market data fails
                        try:
                            unrealized_pnl = pos.unrealizedPNL
                            if unrealized_pnl and avg_cost > 0 and abs(qty) > 0:
                                pnl_pct = (unrealized_pnl / (avg_cost * abs(qty) * 100)) * 100
                                pnl_emoji = "📈" if unrealized_pnl > 0 else "📉"
                                pnl_text = f" {pnl_emoji} ${unrealized_pnl:+.2f} ({pnl_pct:+.1f}%)"
                        except:
                            pass

                    text += f"• {symbol}: {qty} @ ${avg_cost:.2f}{pnl_text}\n"
            else:
                text += "  No open positions\n"

            text += "\n"

            # Open orders - separate brackets from entry orders
            text += f"<b>📋 Open Orders ({len(open_orders)}):</b>\n"
            if open_orders:
                entry_orders, stop_orders, target_orders = self._categorize_orders(open_orders, open_sessions)

                # Debug: Log session bracket tracking
                for session in open_sessions:
                    print(f"[DEBUG] Session {session.session_id[:8]}: stop_id={session.stop_order_id}, target_ids={session.target_order_ids}")

                # Debug: Log all open order IDs
                print(f"[DEBUG] Open order IDs: {[t.order.orderId for t in open_orders]}")

                # Display entry orders
                if entry_orders:
                    text += "  <i>Entry Orders:</i>\n"
                    for trade in entry_orders:
                        contract = trade.contract
                        order = trade.order
                        symbol = contract.localSymbol if hasattr(contract, 'localSymbol') else contract.symbol
                        action = order.action
                        qty = order.totalQuantity
                        price = order.lmtPrice if order.lmtPrice else order.auxPrice
                        status = trade.orderStatus.status
                        text += f"    • {action} {qty} {symbol} @ ${price:.2f} - {status}\n"

                # Display bracket orders
                if stop_orders or target_orders:
                    text += "  <i>Bracket Orders:</i>\n"
                    for trade in stop_orders:
                        contract = trade.contract
                        order = trade.order
                        symbol = contract.localSymbol if hasattr(contract, 'localSymbol') else contract.symbol
                        qty = order.totalQuantity
                        price = order.lmtPrice if order.lmtPrice else order.auxPrice
                        status = trade.orderStatus.status
                        text += f"    • 🛑 STOP: {qty} {symbol} @ ${price:.2f} - {status}\n"

                    for trade in target_orders:
                        contract = trade.contract
                        order = trade.order
                        symbol = contract.localSymbol if hasattr(contract, 'localSymbol') else contract.symbol
                        qty = order.totalQuantity
                        price = order.lmtPrice if order.lmtPrice else order.auxPrice
                        status = trade.orderStatus.status
                        text += f"    • 🎯 TARGET: {qty} {symbol} @ ${price:.2f} - {status}\n"

                if not entry_orders and not stop_orders and not target_orders:
                    text += "  No open orders\n"
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

    async def _handle_server_command(self, cmd: dict) -> str:
        """
        Handle /server command from Telegram.

        Returns bot health and IBKR connection status.
        """
        try:
            import platform

            mode = "📝 DRY-RUN" if self.dry_run else "🔴 LIVE"

            # Calculate uptime
            uptime_str = "Unknown"
            if self.start_time:
                uptime_delta = datetime.now(timezone.utc) - self.start_time
                hours = int(uptime_delta.total_seconds() // 3600)
                minutes = int((uptime_delta.total_seconds() % 3600) // 60)
                uptime_str = f"{hours}h {minutes}m"

            # Build response
            text = f"<b>🖥️ {mode} SERVER HEALTH</b>\n\n"

            # Bot Status
            text += f"<b>🤖 Bot Status</b>\n"
            if self.running:
                text += f"• Status: ✅ Running\n"
            else:
                text += f"• Status: ⚠️ Stopped\n"
            text += f"• Uptime: ⏱️ {uptime_str}\n"
            text += f"• Mode: {mode}\n"
            text += f"\n"

            # IBKR Connection
            text += f"<b>🏦 IBKR Connection</b>\n"
            if self.dry_run:
                text += f"• Status: ⏸️ Disconnected (Paper Mode)\n"
                text += f"• Port: {self.config['ibkr']['port']}\n"
            else:
                if self.executor.connected:
                    text += f"• Status: ✅ Connected\n"
                    text += f"• Host: {self.config['ibkr']['host']}\n"
                    text += f"• Port: {self.config['ibkr']['port']}\n"

                    # Get account balance
                    balance = await self.executor.get_account_balance()
                    if balance:
                        text += f"• Account: 💰 ${balance:,.2f}\n"
                else:
                    text += f"• Status: ❌ Disconnected\n"
                    text += f"• Host: {self.config['ibkr']['host']}\n"
                    text += f"• Port: {self.config['ibkr']['port']}\n"
            text += f"\n"

            # Discord Listener
            text += f"<b>💬 Discord Listener</b>\n"
            if self.discord_listener.running:
                text += f"• Status: ✅ Running\n"
                text += f"• Channels: {len(self.discord_listener.channel_ids)}\n"
                if self.discord_listener.monitored_users:
                    text += f"• Users: {len(self.discord_listener.monitored_users)}\n"
                else:
                    text += f"• Users: All\n"
            else:
                text += f"• Status: ❌ Stopped\n"
            text += f"\n"

            # Session Manager
            text += f"<b>📊 Session Manager</b>\n"
            total_sessions = len(self.session_manager.sessions)
            open_sessions = len([s for s in self.session_manager.sessions.values() if s.state == SessionState.OPEN])
            closed_sessions = len([s for s in self.session_manager.sessions.values() if s.state == SessionState.CLOSED])
            text += f"• Total Sessions: {total_sessions}\n"
            text += f"• Open: 🟢 {open_sessions}\n"
            text += f"• Closed: ⚪ {closed_sessions}\n"
            text += f"\n"

            # System Resources (if psutil available)
            if PSUTIL_AVAILABLE:
                try:
                    cpu_percent = psutil.cpu_percent(interval=0.1)
                    memory = psutil.virtual_memory()
                    disk = psutil.disk_usage('/')

                    text += f"<b>💻 System Resources</b>\n"

                    # Resource usage emojis
                    cpu_emoji = self._get_resource_emoji(cpu_percent, 50, 80)
                    text += f"• CPU: {cpu_emoji} {cpu_percent:.1f}%\n"

                    # Memory
                    mem_percent = memory.percent
                    mem_emoji = self._get_resource_emoji(mem_percent, 70, 90)
                    text += f"• Memory: {mem_emoji} {mem_percent:.1f}% ({memory.used / (1024**3):.1f}GB / {memory.total / (1024**3):.1f}GB)\n"

                    # Disk
                    disk_percent = disk.percent
                    disk_emoji = self._get_resource_emoji(disk_percent, 70, 90)
                    text += f"• Disk: {disk_emoji} {disk_percent:.1f}% ({disk.used / (1024**3):.1f}GB / {disk.total / (1024**3):.1f}GB)\n"
                    text += f"\n"

                    # System Info
                    text += f"<b>🖥️ System Info</b>\n"
                    text += f"• OS: {platform.system()} {platform.release()}\n"
                    text += f"• Python: {platform.python_version()}\n"

                except Exception as e:
                    text += f"<b>💻 System Resources</b>\n"
                    text += f"• Error: ⚠️ {str(e)}\n"
                    text += f"\n"
            else:
                # psutil not available
                text += f"<b>💻 System Resources</b>\n"
                text += f"• Status: ⚠️ Not available (install psutil)\n"
                text += f"\n"

            # Risk Gate Status
            text += f"<b>🛡️ Risk Gate</b>\n"
            # Kill switch is on executor, not risk_gate
            if self.executor.kill_switch_active:
                text += f"• Kill Switch: 🔴 ACTIVE\n"
            else:
                text += f"• Kill Switch: ✅ Inactive\n"
            text += f"• Daily P&L: ${self.risk_gate.daily_pnl:,.2f}\n"
            text += f"• Loss Streak: {self.risk_gate.loss_streak}\n"
            text += f"\n"

            # Telegram Status
            text += f"<b>📱 Telegram Bot</b>\n"
            if self.notifier and self.notifier.enabled:
                text += f"• Status: ✅ Enabled\n"
                text += f"• Chat ID: {self.notifier.chat_id}\n"
            else:
                text += f"• Status: ⚠️ Disabled\n"

            # Timestamp
            text += f"\n<i>🕐 Updated: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}</i>"

            return text

        except Exception as e:
            return f"❌ Error getting server health: {str(e)}"

    async def _handle_closeall_command(self, cmd: dict) -> str:
        """
        Handle /closeall command from Telegram.

        Emergency command to close ALL IBKR positions regardless of session state.
        Used to handle orphaned positions, SHORT positions, or emergency exits.
        """
        try:
            if self.dry_run:
                return "❌ Cannot close positions in DRY-RUN mode"

            if not self.executor.connected:
                return "❌ Not connected to IBKR"

            # Get all current positions
            positions = await self.executor.get_positions()

            if not positions:
                return "✅ No positions to close"

            text = f"<b>🚨 EMERGENCY: Closing All Positions</b>\n\n"
            text += f"Found {len(positions)} position(s):\n"

            closed_count = 0
            failed_count = 0

            for pos in positions:
                contract = pos.contract
                quantity = pos.position
                avg_cost = pos.avgCost

                symbol = f"{contract.symbol} {contract.strike}{contract.right}" if hasattr(contract, 'strike') else contract.symbol
                position_type = "SHORT" if quantity < 0 else "LONG"

                text += f"\n• {symbol}: {quantity} ({position_type})\n"

                try:
                    # CRITICAL: Cancel bracket orders FIRST to prevent SHORT positions
                    # Find and cancel brackets before closing position
                    session_to_close = None
                    if hasattr(contract, 'strike'):
                        session_key = f"{contract.symbol} {contract.strike} {contract.right} {contract.lastTradeDateOrContractMonth}"
                        for session in self.session_manager.sessions.values():
                            if session.state == SessionState.OPEN:
                                sess_key = f"{session.underlying} {session.strike} {session.direction.value[0]} {session.expiry.replace('-', '')}"
                                if sess_key == session_key:
                                    session_to_close = session

                                    # Cancel brackets FIRST
                                    if session.stop_order_id or session.target_order_ids:
                                        print(f"    Cancelling brackets for {symbol}...")
                                        await self._cancel_session_brackets(session)
                                        text += f"  🛑 Cancelled {1 if session.stop_order_id else 0 + len(session.target_order_ids or [])} bracket order(s)\n"
                                    break

                    # Determine order action (BUY to close SHORT, SELL to close LONG)
                    action = "BUY" if quantity < 0 else "SELL"
                    close_quantity = abs(quantity)

                    # Set exchange for proper routing (required by IBKR)
                    contract.exchange = "SMART"

                    # Use MARKET order for fast emergency close
                    from ib_insync import MarketOrder
                    order = MarketOrder(action, close_quantity)
                    trade = self.executor.ib.placeOrder(contract, order)

                    # Wait briefly for fill
                    filled = await self.executor._wait_for_fill(trade, timeout=10)

                    if filled:
                        fill_price = trade.orderStatus.avgFillPrice

                        # Calculate P&L correctly for options
                        # fill_price is premium (e.g., $0.10)
                        # avg_cost is already in dollars per contract (e.g., $12.00)
                        # For options: convert fill_price to dollars first
                        if hasattr(contract, 'strike'):
                            fill_value = fill_price * 100  # Convert premium to dollar value
                            pnl = (fill_value - avg_cost) * quantity
                        else:
                            # For stocks/other securities
                            pnl = (fill_price - avg_cost) * quantity

                        text += f"  ✅ Closed @ ${fill_price:.2f}"
                        if pnl != 0:
                            pnl_emoji = "💰" if pnl > 0 else "📉"
                            text += f" | {pnl_emoji} P&L: ${pnl:+,.2f}"
                        text += f"\n"

                        closed_count += 1

                        # Close any associated sessions (already found earlier)
                        if session_to_close:
                            now = datetime.now(timezone.utc)
                            session_to_close.state = SessionState.CLOSED
                            session_to_close.closed_at = now
                            session_to_close.updated_at = now
                            session_to_close.exit_reason = "EMERGENCY_CLOSEALL"
                            session_to_close.total_quantity = 0
                            session_to_close.exit_price = fill_price
                            session_to_close.realized_pnl = pnl if hasattr(contract, 'strike') else 0
                    else:
                        text += f"  ⚠️ Close order timed out\n"
                        failed_count += 1

                except Exception as e:
                    text += f"  ❌ Error: {str(e)}\n"
                    failed_count += 1

            text += f"\n<b>Summary:</b>\n"
            text += f"• Closed: {closed_count}\n"
            text += f"• Failed: {failed_count}\n"
            text += f"\n<i>Time: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}</i>"

            return text

        except Exception as e:
            return f"❌ Error executing closeall: {str(e)}"

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

                # Validate NEW events have required fields and sufficient confidence
                if event.event_type == EventType.NEW:
                    if not all([event.underlying, event.direction, event.strike]):
                        print(f"⚠️ NEW event missing required fields (underlying/direction/strike)")
                        print(f"  Reclassifying as IGNORE (LLM was too aggressive)")
                        event.event_type = EventType.IGNORE
                    elif event.parsing_confidence and event.parsing_confidence < 0.7:
                        print(f"⚠️ NEW event has low confidence ({event.parsing_confidence:.2f})")
                        print(f"  Reclassifying as IGNORE (insufficient confidence)")
                        event.event_type = EventType.IGNORE

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

            # Update account balance and get unrealized P&L
            unrealized_pnl = 0.0
            if not self.dry_run and self.executor.connected:
                # Update balance
                balance = await self.executor.get_account_balance()
                if balance:
                    self.risk_gate.update_account_balance(balance)
                    print(f"  Account balance updated: ${balance:,.2f}")

                # Get unrealized P&L
                unrealized_pnl = await self.executor.get_unrealized_pnl()
                print(f"  Current unrealized P&L: ${unrealized_pnl:+.2f}")

            risk_result = self.risk_gate.validate(
                event=event,
                session=session,
                unrealized_pnl=unrealized_pnl,
            )

            print(f"{'✓' if risk_result.decision == RiskDecision.APPROVE else '✗'} {risk_result.decision}: {risk_result.reason}")

            if risk_result.decision == RiskDecision.REJECT:
                print("  ACTION: NO TRADE (risk gate rejection)")
                if risk_result.failed_checks:
                    for check in risk_result.failed_checks:
                        print(f"    - {check}")
                return

            # Cash check for NEW trades (Cash account with T+1 settlement)
            if event.event_type == EventType.NEW and not self.dry_run and self.executor.connected:
                cash_details = self.executor.get_cash_details()
                if cash_details:
                    available_cash = cash_details.get('available_funds') or cash_details.get('settled_cash')
                    if available_cash is not None:
                        # Estimate cost for 1 contract (will be refined after position sizing)
                        estimated_cost = (event.entry_price or 0.50) * 100  # Premium × 100
                        if available_cash < estimated_cost:
                            print(f"⚠️ INSUFFICIENT SETTLED CASH")
                            print(f"  Available: ${available_cash:,.2f}")
                            print(f"  Estimated cost: ${estimated_cost:,.2f}")
                            print(f"  ACTION: NO TRADE (waiting for T+1 settlement)")
                            await self.telegram.send_message(
                                f"⚠️ <b>Trade Blocked - Insufficient Cash</b>\n\n"
                                f"Cannot enter {event.underlying} {event.strike}{event.direction.value[0]}\n"
                                f"Available: ${available_cash:,.2f}\n"
                                f"Needed: ~${estimated_cost:,.2f}\n\n"
                                f"<i>Waiting for T+1 settlement from previous trades</i>"
                            )
                            return
                        else:
                            print(f"✓ Settled cash check passed: ${available_cash:,.2f} available")

            # Step 4: Calculate position size and stops/targets
            print("\n[4/5] Calculating position size and risk parameters...")
            if event.is_actionable():
                quantity = self.risk_gate.calculate_position_size(
                    event=event, session=session
                )
                print(f"✓ Position size: {quantity} contracts")

                # Check if quantity is 0 (already at max position)
                if quantity == 0:
                    print(f"⚠️ Position size = 0 (already at MAX_CONTRACTS limit)")
                    print(f"  Current: {session.total_quantity} contracts")
                    print(f"  Max allowed: {self.config['risk']['max_contracts']}")
                    print(f"  ACTION: NO TRADE (position limit reached)")

                    # Send Telegram notification
                    if self.notifier:
                        await self.notifier.send_message(
                            f"⚠️ <b>Trade Blocked - Position Limit</b>\n\n"
                            f"{event.underlying} {event.strike}{event.direction.value[0]}\n\n"
                            f"Current: {session.total_quantity} contracts\n"
                            f"Max allowed: {self.config['risk']['max_contracts']}\n\n"
                            f"<i>Cannot add more contracts - already at maximum</i>"
                        )
                    return

                # Calculate stop loss and target based on CONFIG (ignore Discord targets)
                if event.event_type == EventType.NEW:
                    # CRITICAL: Clear Discord-parsed targets for NEW orders
                    # Brackets will be calculated by EXECUTOR from ACTUAL FILL PRICE
                    # This ensures brackets use real execution price, not Discord alert price
                    event.stop_loss = None  # Executor will calculate from actual fill
                    event.targets = None    # Executor will calculate from actual fill

                    print(f"  ℹ️  Brackets will be calculated from actual fill price using config:")
                    print(f"     - Stop: {self.config['risk']['auto_stop_loss_percent']}% below fill")
                    print(f"     - Target: {self.config['risk']['risk_reward_ratio']}x risk above fill")
            else:
                print("✓ Non-actionable event (informational only)")
                return

            # Step 5: Execute
            print("\n[5/5] Executing order...")

            if self.dry_run:
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
                        dry_run=True,
                    )

                # Log simulated result
                from ..execution.executor import OrderResult, OrderStatus
                simulated_result = OrderResult(
                    success=True,
                    status=OrderStatus.FILLED,
                    filled_price=event.entry_price,
                    message="Simulated fill (dry-run mode)"
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
                        dry_run=True,
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
                        dry_run=False,
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

                # Check if session closed after execution (EXIT, TRIM to zero, etc.)
                if result.success and session.state == SessionState.CLOSED:
                    print(f"  ⓘ Session closed: {session.exit_reason}")
                    self.logger.log_session_closed(
                        session,
                        reason=session.exit_reason or "ORDER_EXECUTION",
                        final_pnl=session.realized_pnl
                    )

                # Send Telegram notification for order fill
                if self.notifier:
                    await self.notifier.notify_order_filled(
                        session=session,
                        event_type=event.event_type,
                        result=result,
                        dry_run=False,
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

    async def _on_bracket_filled(self, session, event_type: EventType, result: OrderResult):
        """
        Callback when bracket order fills (stop loss or take profit).

        Args:
            session: The TradeSession that closed
            event_type: EventType.SL or EventType.TP
            result: OrderResult with fill details
        """
        # Log to file
        self.logger.log_order_result(session, event_type, result)

        # Close the session in logs
        self.logger.log_session_closed(
            session,
            reason=session.exit_reason,
            final_pnl=session.realized_pnl
        )

        # Send Telegram notification
        if self.notifier:
            await self.notifier.notify_order_filled(
                session=session,
                event_type=event_type,
                result=result,
                dry_run=self.dry_run
            )

        # Log to console
        symbol = f"{session.underlying} {session.strike}{session.direction.value[0] if session.direction else '?'}"
        exit_type = "STOP LOSS" if event_type == EventType.SL else "TAKE PROFIT"
        print(f"\n{'='*60}")
        print(f"{exit_type} FILLED: {symbol}")
        print(f"Exit Price: ${result.filled_price:.2f}")
        print(f"P&L: ${session.realized_pnl:+,.2f}")
        print(f"{'='*60}\n")

    async def _connection_monitor_task(self):
        """
        Background task to monitor IBKR connection and auto-reconnect if needed.

        Checks connection every 60 seconds and attempts reconnection if disconnected.
        """
        print("Connection monitor active (checks every 60 seconds)")

        while self.running:
            await asyncio.sleep(60)  # Check every minute

            if not self.executor.connected:
                print("⚠️ Connection monitor detected disconnection. Attempting reconnection...")

                # Attempt to reconnect
                success = await self.executor.reconnect()

                if not success:
                    print("❌ Reconnection failed. Will retry on next check...")

                    # Send alert if reconnection keeps failing
                    if self.executor.reconnect_attempts >= 5 and self.notifier:
                        await self.notifier.send_message(
                            "<b>⚠️ IBKR CONNECTION ISSUE</b>\n\n"
                            f"Failed to reconnect after {self.executor.reconnect_attempts} attempts.\n"
                            "Bot will continue attempting to reconnect.\n\n"
                            "<i>Please check IBKR Gateway is running.</i>"
                        )

    async def _on_ibkr_disconnected(self):
        """Callback when IBKR connection is lost."""
        print("🔴 IBKR disconnected - auto-reconnection initiated")

        # Send Telegram notification
        if self.notifier:
            await self.notifier.send_message(
                "<b>🔴 IBKR DISCONNECTED</b>\n\n"
                "Connection to IBKR Gateway lost.\n"
                "Auto-reconnection will attempt shortly.\n\n"
                "<i>Bracket orders are still active on IBKR side.</i>"
            )

    async def _on_ibkr_reconnected(self):
        """Callback when IBKR connection is restored."""
        print("🟢 IBKR reconnected successfully")

        # Send Telegram notification
        if self.notifier:
            await self.notifier.send_message(
                "<b>✅ IBKR RECONNECTED</b>\n\n"
                "Connection to IBKR Gateway restored.\n"
                "Bot is now fully operational.\n\n"
                f"<i>Reconnected at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}</i>"
            )

    async def _position_reconciliation_task(self):
        """
        Background task to reconcile sessions with actual IBKR positions.

        Runs every 60 seconds. For each OPEN session:
        - Check if position still exists in IBKR
        - If position is 0 (or doesn't exist), auto-close session

        This handles cases where positions are manually closed outside the bot.
        """
        print("Position reconciliation active (checks every 60 seconds, 3-minute grace period)")

        while self.running:
            await asyncio.sleep(60)

            if self.dry_run or not self.executor.connected:
                continue  # Skip in dry-run mode or when disconnected

            try:
                # Get current IBKR positions
                ibkr_positions = await self.executor.get_positions()

                # Build position lookup: contract key -> quantity
                position_map = {}
                for pos in ibkr_positions:
                    contract = pos.contract
                    # Create key: "SPY 685 C 20251217"
                    key = f"{contract.symbol} {contract.strike} {contract.right} {contract.lastTradeDateOrContractMonth}"
                    position_map[key] = pos.position

                # Check all OPEN sessions
                open_sessions = [s for s in self.session_manager.sessions.values() if s.state == SessionState.OPEN]

                # Track which positions we've matched to sessions
                # IMPORTANT: Mark ALL open sessions as matched (even within grace period)
                # to prevent false "orphaned" warnings for new positions
                matched_positions = set()

                for session in open_sessions:
                    # Build session key
                    session_key = f"{session.underlying} {session.strike} {session.direction.value[0]} {session.expiry.replace('-', '')}"

                    # Mark this position as matched (tracked by a session)
                    # This prevents false "orphaned" warnings
                    if session_key in position_map:
                        matched_positions.add(session_key)

                    # Skip recently updated sessions for reconciliation checks (grace period for settlement)
                    # IBKR positions take time to settle after fills
                    time_since_update = (datetime.now(timezone.utc) - session.updated_at).total_seconds()
                    if time_since_update < 180:  # 3 minutes grace period
                        continue  # Don't check for position-gone yet, still settling

                    # Check if position exists (only for sessions past grace period)
                    ibkr_quantity = position_map.get(session_key, 0)

                    if ibkr_quantity == 0 and session.total_quantity > 0:
                        # Position is gone but session thinks it's open → Auto-close
                        print(f"⚠️ Position reconciliation: {session_key} position is 0, auto-closing session")

                        session.state = SessionState.CLOSED
                        session.closed_at = datetime.now(timezone.utc)
                        session.exit_reason = "POSITION_RECONCILIATION"
                        session.total_quantity = 0

                        # Cancel any open bracket orders
                        if session.stop_order_id or session.target_order_ids:
                            await self._cancel_session_brackets(session)

                        # Log closure
                        self.logger.log_session_closed(
                            session,
                            reason="Position reconciliation (manually closed outside bot)",
                            final_pnl=session.realized_pnl
                        )

                        # Send notification with P&L if available
                        if self.notifier:
                            pnl_text = ""
                            if session.realized_pnl != 0:
                                pnl_emoji = "💰" if session.realized_pnl > 0 else "📉"
                                pnl_text = f"P&L: {pnl_emoji} ${session.realized_pnl:+,.2f}\n"

                            await self.notifier.send_message(
                                f"<b>🔄 Session Auto-Closed</b>\n\n"
                                f"<b>Position:</b> {session_key}\n"
                                f"<b>Reason:</b> Manually exited outside bot\n"
                                f"{pnl_text}\n"
                                f"<i>Session closed via position reconciliation</i>"
                            )

                # Reverse check: IBKR has positions that bot doesn't track
                unmatched_positions = set(position_map.keys()) - matched_positions

                # CRITICAL: Check for SHORT positions (negative quantity)
                short_positions = {key: qty for key, qty in position_map.items() if qty < 0}
                if short_positions:
                    print(f"🚨 CRITICAL: {len(short_positions)} SHORT position(s) detected!")
                    for pos_key, quantity in short_positions.items():
                        print(f"   - {pos_key}: {quantity} contracts (SHORT)")
                        print(f"     🚨 Bot only trades LONG - this should NEVER happen!")
                        print(f"     🚨 Likely cause: Bracket filled after session closed")
                        print(f"     🚨 ACTION REQUIRED: Close manually in TWS immediately!")

                    # Send urgent Telegram alert
                    if self.notifier:
                        short_text = "\n".join([f"• {key}: {qty} contracts" for key, qty in short_positions.items()])
                        await self.notifier.send_message(
                            f"<b>🚨 CRITICAL: SHORT POSITION DETECTED</b>\n\n"
                            f"The bot has detected SHORT positions:\n\n"
                            f"{short_text}\n\n"
                            f"<b>⚠️ This bot only trades LONG positions!</b>\n\n"
                            f"<b>Likely cause:</b>\n"
                            f"• Bracket order filled after session closed\n"
                            f"• Race condition in position reconciliation\n\n"
                            f"<b>🚨 IMMEDIATE ACTION REQUIRED:</b>\n"
                            f"1. Open TWS\n"
                            f"2. BUY TO CLOSE these positions NOW\n"
                            f"3. Check for unlimited loss risk\n\n"
                            f"<i>Time: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}</i>"
                        )

                if unmatched_positions:
                    print(f"⚠️ WARNING: {len(unmatched_positions)} IBKR position(s) have no active session:")
                    for pos_key in unmatched_positions:
                        quantity = position_map[pos_key]
                        is_short = quantity < 0
                        print(f"   - {pos_key}: {quantity} contracts{' (SHORT!)' if is_short else ''}")
                        if not is_short:
                            print(f"     This position was likely opened manually or is an orphaned bracket order")

                    # Send Telegram warning
                    if self.notifier and unmatched_positions:
                        positions_text = "\n".join([f"• {key}: {position_map[key]} contracts" for key in unmatched_positions])
                        await self.notifier.send_message(
                            f"<b>⚠️ Orphaned Positions Detected</b>\n\n"
                            f"IBKR has positions that the bot is not tracking:\n\n"
                            f"{positions_text}\n\n"
                            f"<b>Possible causes:</b>\n"
                            f"• Position opened manually outside bot\n"
                            f"• Bracket order filled after session closed\n"
                            f"• Bug in session management\n\n"
                            f"<i>⚠️ Please check TWS and close manually if needed</i>"
                        )

            except Exception as e:
                print(f"⚠️ Error in position reconciliation: {e}")

    async def _eod_auto_close_task(self):
        """
        Background task to auto-close all open positions at end of trading day.

        At TRADING_HOURS_END (default: 20:00 UTC = 4:00 PM ET):
        - Find all OPEN sessions
        - Submit market orders to close positions
        - Close sessions with reason "EOD_AUTO_CLOSE"
        """
        eod_time_str = self.config["risk"]["trading_hours_end"]
        try:
            hour, minute = map(int, eod_time_str.split(":"))
            eod_time = time(hour=hour, minute=minute)
        except (ValueError, TypeError, AttributeError):
            eod_time = time(hour=20, minute=0)  # Default to 8 PM UTC

        print(f"EOD auto-close will run at {eod_time_str} UTC")

        while self.running:
            now = datetime.now(timezone.utc)
            target_time = datetime.combine(now.date(), eod_time, tzinfo=timezone.utc)

            # If target time already passed today, schedule for tomorrow
            if now > target_time:
                from datetime import timedelta
                target_time += timedelta(days=1)

            # Wait until EOD time
            seconds_until_eod = (target_time - now).total_seconds()
            await asyncio.sleep(seconds_until_eod)

            if not self.running:
                break

            # Execute EOD close
            if self.dry_run:
                print("\n[EOD AUTO-CLOSE] Paper mode - would close all positions")
            else:
                print("\n[EOD AUTO-CLOSE] Closing all open positions...")
                await self._execute_eod_close()

            # Wait a bit to avoid running multiple times
            await asyncio.sleep(60)

    async def _execute_eod_close(self):
        """
        Execute end-of-day close for all open sessions.

        Uses market orders for fast execution at market close.
        """
        from ib_insync import MarketOrder

        open_sessions = [s for s in self.session_manager.sessions.values() if s.state == SessionState.OPEN]

        if not open_sessions:
            print("  No open sessions to close")
            return

        print(f"  Closing {len(open_sessions)} open session(s)...")

        for session in open_sessions:
            try:
                # Build contract
                contract = self.executor._build_contract_from_session(session)
                qualified = await self.executor.ib.qualifyContractsAsync(contract)

                if not qualified:
                    print(f"  ⚠️ Could not qualify contract for {session.underlying} {session.strike}")
                    continue

                contract = qualified[0]

                # Cancel existing brackets
                await self._cancel_session_brackets(session)

                # Submit MARKET order for fast execution
                market_order = MarketOrder("SELL", session.total_quantity)
                trade = self.executor.ib.placeOrder(contract, market_order)

                # Wait briefly for fill
                filled = await self.executor._wait_for_fill(trade, timeout=10)

                if filled:
                    fill_price = trade.orderStatus.avgFillPrice
                    pnl = self.executor._calculate_session_pnl(session, fill_price)

                    # Update session
                    session.state = SessionState.CLOSED
                    session.closed_at = datetime.now(timezone.utc)
                    session.exit_reason = "EOD_AUTO_CLOSE"
                    session.exit_price = fill_price
                    session.realized_pnl = pnl
                    session.total_quantity = 0

                    print(f"  ✓ Closed {session.underlying} {session.strike} @ ${fill_price:.2f} | P&L: ${pnl:+,.2f}")

                    # Log and notify
                    self.logger.log_session_closed(session, reason="EOD Auto-Close", final_pnl=pnl)

                    if self.notifier:
                        await self.notifier.send_message(
                            f"<b>🌙 EOD Auto-Close</b>\n\n"
                            f"Position: {session.underlying} {session.strike}\n"
                            f"Exit Price: ${fill_price:.2f}\n"
                            f"P&L: ${pnl:+,.2f}\n\n"
                            f"<i>All positions closed at end of trading day</i>"
                        )
                else:
                    print(f"  ⚠️ EOD close timeout for {session.underlying} {session.strike}")

            except Exception as e:
                print(f"  ⚠️ Error closing session {session.session_id}: {e}")

    async def _cancel_session_brackets(self, session: TradeSession):
        """Cancel all bracket orders for a session."""
        order_ids_to_cancel = []

        if session.stop_order_id:
            order_ids_to_cancel.append(session.stop_order_id)
        if session.target_order_ids:
            order_ids_to_cancel.extend(session.target_order_ids)

        if order_ids_to_cancel:
            await self.executor._cancel_sibling_orders(order_ids_to_cancel)


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
            "port": int(os.getenv("IBKR_PORT", "7497")),  # 7497 = TWS live, 7496 = TWS paper, 4001 = Gateway live, 4002 = Gateway paper
            "client_id": int(os.getenv("IBKR_CLIENT_ID", "1")),
            "force_market_orders": os.getenv("FORCE_MARKET_ORDERS", "false").lower() == "true",
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
            "initial_contracts": int(os.getenv("INITIAL_CONTRACTS", "1")),
            "max_contracts": int(os.getenv("MAX_CONTRACTS", "2")),
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
        "dry_run": os.getenv("DRY_RUN", "true").lower() == "true",
    }

    # Create and start orchestrator
    orchestrator = TradingOrchestrator(config)
    await orchestrator.start()


if __name__ == "__main__":
    asyncio.run(main())
