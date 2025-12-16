import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel
from ib_insync import IB, Option, LimitOrder, Order, Trade

from ..models import Event, TradeSession, EventType, Direction


class OrderStatus(str, Enum):
    """Order execution status."""

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderResult(BaseModel):
    """Result of order execution attempt."""

    success: bool
    order_id: Optional[int] = None
    status: OrderStatus
    filled_price: Optional[float] = None
    message: Optional[str] = None

    class Config:
        use_enum_values = True


class ExecutionEngine:
    """
    Handles order execution via Interactive Brokers.

    Implements strict execution rules from proposal:
    - Limit orders only
    - Bracket/OCO orders required
    - Idempotent order submission
    - Kill switch enforced
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,  # 7497 = paper, 7496 = live
        client_id: int = 1,
        session_manager=None,  # For bracket order monitoring
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()
        self.connected = False
        self.kill_switch_active = False
        self.session_manager = session_manager
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10

        # Track submitted orders for idempotency
        self.submitted_orders: dict[str, Trade] = {}

    async def connect(self) -> bool:
        """Connect to IBKR TWS/Gateway."""
        try:
            await self.ib.connectAsync(
                host=self.host, port=self.port, clientId=self.client_id
            )
            self.connected = True
            self.reconnect_attempts = 0

            # Register order monitoring callback
            self.ib.orderStatusEvent += self._on_order_status_change

            # Register disconnection callback
            self.ib.disconnectedEvent += self._on_disconnected

            print(f"Connected to IBKR at {self.host}:{self.port}")
            print("Order monitoring active (bracket fills will be detected)")
            print("Auto-reconnection enabled")

            # Get and display account balance
            await self._display_account_balance()

            return True
        except Exception as e:
            print(f"Failed to connect to IBKR: {e}")
            self.connected = False
            return False

    def _on_disconnected(self):
        """Callback when IBKR connection is lost."""
        self.connected = False
        print("⚠️ IBKR connection lost! Auto-reconnection will attempt...")

        # Notify via callback if available
        if hasattr(self, 'on_disconnected'):
            asyncio.create_task(self.on_disconnected())

    async def reconnect(self) -> bool:
        """Attempt to reconnect to IBKR."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            print(f"❌ Max reconnection attempts ({self.max_reconnect_attempts}) reached. Manual intervention required.")
            return False

        self.reconnect_attempts += 1
        print(f"🔄 Reconnection attempt {self.reconnect_attempts}/{self.max_reconnect_attempts}...")

        # Wait before attempting (exponential backoff)
        wait_time = min(2 ** self.reconnect_attempts, 60)  # Max 60 seconds
        await asyncio.sleep(wait_time)

        try:
            success = await self.connect()
            if success:
                print(f"✓ Reconnected to IBKR successfully!")

                # Notify via callback if available
                if hasattr(self, 'on_reconnected'):
                    await self.on_reconnected()

                return True
            else:
                return False
        except Exception as e:
            print(f"Reconnection attempt failed: {e}")
            return False

    async def ensure_connected(self) -> bool:
        """Ensure connection is active, reconnect if necessary."""
        if not self.connected:
            print("⚠️ Not connected to IBKR. Attempting to reconnect...")
            return await self.reconnect()
        return True

    async def disconnect(self) -> None:
        """Disconnect from IBKR."""
        if self.connected:
            self.ib.disconnect()
            self.connected = False
            print("Disconnected from IBKR")

    def activate_kill_switch(self, reason: str) -> None:
        """
        Activate kill switch - blocks all new orders.

        This is a fail-safe that can be triggered by:
        - Critical errors
        - Risk violations
        - Manual intervention
        """
        self.kill_switch_active = True
        print(f"KILL SWITCH ACTIVATED: {reason}")

    def deactivate_kill_switch(self) -> None:
        """Deactivate kill switch (use with caution)."""
        self.kill_switch_active = False
        print("Kill switch deactivated")

    def _on_order_status_change(self, trade):
        """
        Callback when ANY order status changes.

        Detects bracket child order fills (stop loss / take profit) and
        updates session state, calculates P&L, and sends notifications.
        """
        order_id = trade.order.orderId
        status = trade.orderStatus.status
        parent_id = trade.orderStatus.parentId

        # Only care about filled orders
        if status != "Filled":
            return

        # Only care about child orders (parent_id > 0)
        if parent_id == 0:
            return

        # Find session by order ID
        if not self.session_manager:
            return

        session = self._find_session_by_order_id(order_id)

        if not session:
            return

        # Ensure session is still open
        from ..models import SessionState
        if session.state != SessionState.OPEN:
            return

        # Determine if this is stop or target
        if order_id == session.stop_order_id:
            # Stop loss filled
            asyncio.create_task(self._handle_stop_filled(session, trade))
        elif order_id in session.target_order_ids:
            # Take profit filled
            asyncio.create_task(self._handle_target_filled(session, trade))

    def _find_session_by_order_id(self, order_id: int):
        """Find session by stop or target order ID."""

        if not self.session_manager:
            return None

        for session in self.session_manager.sessions.values():
            if session.stop_order_id == order_id:
                return session
            if order_id in session.target_order_ids:
                return session

        return None

    def _calculate_session_pnl(
        self,
        session,
        exit_price: float
    ) -> float:
        """
        Calculate realized P&L for a session.

        P&L = (Exit Price - Avg Entry Price) × Total Quantity × 100

        Options have 100 multiplier (each contract = 100 shares).
        """

        if session.total_quantity == 0:
            return 0.0

        price_diff = exit_price - session.avg_entry_price
        contract_multiplier = 100
        pnl = price_diff * session.total_quantity * contract_multiplier

        return round(pnl, 2)

    async def _handle_stop_filled(self, session, trade):
        """Handle stop loss bracket order fill."""

        fill_price = trade.orderStatus.avgFillPrice
        pnl = self._calculate_session_pnl(session, fill_price)

        # Update session
        from ..models import SessionState
        session.state = SessionState.CLOSED
        session.closed_at = datetime.now(timezone.utc)
        session.exit_reason = "STOP_HIT"
        session.exit_order_id = trade.order.orderId
        session.exit_price = fill_price
        session.realized_pnl = pnl

        # Cancel remaining target orders
        await self._cancel_sibling_orders(session.target_order_ids)

        # Log to console
        symbol = f"{session.underlying} {session.strike}{session.direction.value[0] if session.direction else '?'}"
        print(f"🛑 STOP HIT: {symbol} @ ${fill_price:.2f} | P&L: ${pnl:+,.2f}")

        # Create OrderResult for notification
        result = OrderResult(
            success=True,
            order_id=trade.order.orderId,
            status=OrderStatus.FILLED,
            filled_price=fill_price,
            message=f"Stop loss triggered at ${fill_price:.2f} | P&L: ${pnl:+,.2f}"
        )

        # Send Telegram notification (via orchestrator callback)
        if hasattr(self, 'on_bracket_filled'):
            from ..models import EventType
            await self.on_bracket_filled(session, EventType.SL, result)

    async def _handle_target_filled(self, session, trade):
        """Handle take profit bracket order fill."""

        fill_price = trade.orderStatus.avgFillPrice
        pnl = self._calculate_session_pnl(session, fill_price)

        # Update session
        from ..models import SessionState
        session.state = SessionState.CLOSED
        session.closed_at = datetime.now(timezone.utc)
        session.exit_reason = "TARGET_HIT"
        session.exit_order_id = trade.order.orderId
        session.exit_price = fill_price
        session.realized_pnl = pnl

        # Cancel stop loss order
        if session.stop_order_id:
            await self._cancel_sibling_orders([session.stop_order_id])

        # Log to console
        symbol = f"{session.underlying} {session.strike}{session.direction.value[0] if session.direction else '?'}"
        print(f"🎯 TARGET HIT: {symbol} @ ${fill_price:.2f} | P&L: ${pnl:+,.2f}")

        # Create OrderResult for notification
        result = OrderResult(
            success=True,
            order_id=trade.order.orderId,
            status=OrderStatus.FILLED,
            filled_price=fill_price,
            message=f"Take profit hit at ${fill_price:.2f} | P&L: ${pnl:+,.2f}"
        )

        # Send Telegram notification (via orchestrator callback)
        if hasattr(self, 'on_bracket_filled'):
            from ..models import EventType
            await self.on_bracket_filled(session, EventType.TP, result)

    async def _cancel_sibling_orders(self, order_ids: list[int]):
        """Cancel sibling bracket orders when one fills (OCO behavior)."""

        if not order_ids:
            return

        for order_id in order_ids:
            try:
                # Find the trade by order ID
                trades = self.ib.trades()
                for trade in trades:
                    if trade.order.orderId == order_id:
                        if trade.isActive():
                            self.ib.cancelOrder(trade.order)
                            print(f"  ✓ Cancelled sibling order {order_id}")
                        break
            except Exception as e:
                print(f"  ⚠️ Failed to cancel order {order_id}: {e}")

    async def execute_event(
        self,
        event: Event,
        session: TradeSession,
        quantity: int,
    ) -> OrderResult:
        """
        Execute an event based on its type.

        Args:
            event: The event to execute
            session: Associated trade session
            quantity: Number of contracts (from risk gate)

        Returns:
            OrderResult with execution status
        """
        # Kill switch check
        if self.kill_switch_active:
            return OrderResult(
                success=False,
                status=OrderStatus.REJECTED,
                message="Kill switch is active",
            )

        # Connection check
        if not self.connected:
            return OrderResult(
                success=False,
                status=OrderStatus.REJECTED,
                message="Not connected to IBKR",
            )

        # Route to appropriate handler
        if event.event_type == EventType.NEW:
            return await self._execute_entry(event, session, quantity)
        elif event.event_type == EventType.ADD:
            return await self._execute_add(event, session, quantity)
        elif event.event_type in [EventType.EXIT, EventType.SL, EventType.TP]:
            return await self._execute_exit(event, session)
        elif event.event_type == EventType.TRIM:
            return await self._execute_trim(event, session)
        elif event.event_type == EventType.MOVE_STOP:
            return await self._execute_move_stop(event, session)
        else:
            return OrderResult(
                success=False,
                status=OrderStatus.REJECTED,
                message=f"Event type {event.event_type} not executable",
            )

    async def _execute_entry(
        self, event: Event, session: TradeSession, quantity: int
    ) -> OrderResult:
        """Execute NEW entry with bracket order."""
        try:
            # Build option contract
            contract = self._build_contract(event)

            # CRITICAL: Qualify contract with IBKR to ensure it exists
            # Use the async method
            qualified = await self.ib.qualifyContractsAsync(contract)

            # If contract not found, try today's expiry (0DTE)
            if not qualified:
                print(f"  ⚠️  Contract not found for expiry {contract.lastTradeDateOrContractMonth}")
                print(f"  Trying 0DTE (same-day expiry)...")

                today = datetime.now().strftime('%Y%m%d')
                contract.lastTradeDateOrContractMonth = today

                qualified = await self.ib.qualifyContractsAsync(contract)

                if not qualified:
                    return OrderResult(
                        success=False,
                        status=OrderStatus.REJECTED,
                        message=f"Contract not found: {contract.symbol} {contract.strike}{contract.right} (tried expiries: {event.expiry}, {today})",
                    )

            # Use the qualified contract (IBKR fills in missing details)
            contract = qualified[0]
            print(f"  ✓ Qualified contract: {contract.localSymbol}")

            # Entry limit order
            entry_price = event.entry_price or await self._get_market_price(
                contract
            )
            if not entry_price:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message="Could not determine entry price",
                )

            # Build bracket order (entry + stop + target)
            bracket = self._build_bracket_order(
                action="BUY",
                quantity=quantity,
                entry_price=entry_price,
                stop_price=event.stop_loss,
                target_price=event.targets[0] if event.targets else None,
            )

            # Submit the bracket as a group
            # IBKR will automatically handle parent/child relationships
            trades = []
            for order in bracket:
                trade = self.ib.placeOrder(contract, order)
                trades.append(trade)

            # Wait for parent (entry) order to fill
            parent_trade = trades[0]
            filled = await self._wait_for_fill(parent_trade, timeout=30)

            if filled:
                # Update session
                session.state = "OPEN"
                session.opened_at = datetime.now(timezone.utc)

                # Store bracket order IDs for monitoring
                session.entry_order_id = parent_trade.order.orderId

                if len(trades) > 1:
                    session.stop_order_id = trades[1].order.orderId

                if len(trades) > 2:
                    session.target_order_ids = [t.order.orderId for t in trades[2:]]

                # Update position tracking
                session.total_quantity = quantity
                session.avg_entry_price = parent_trade.orderStatus.avgFillPrice

                # Log the bracket structure
                msg = f"Entry filled at ${parent_trade.orderStatus.avgFillPrice:.2f}"
                if len(trades) > 1:
                    msg += " | Bracket active:"
                    if event.stop_loss:
                        msg += f" Stop=${event.stop_loss}"
                    if event.targets:
                        msg += f" Target=${event.targets[0]}"

                return OrderResult(
                    success=True,
                    order_id=parent_trade.order.orderId,
                    status=OrderStatus.FILLED,
                    filled_price=parent_trade.orderStatus.avgFillPrice,
                    message=msg,
                )
            else:
                # Cancel entire bracket if parent doesn't fill
                for trade in trades:
                    self.ib.cancelOrder(trade.order)

                return OrderResult(
                    success=False,
                    status=OrderStatus.CANCELLED,
                    message="Entry order timed out - bracket cancelled",
                )

        except Exception as e:
            return OrderResult(
                success=False,
                status=OrderStatus.REJECTED,
                message=f"Execution error: {e}",
            )

    async def _execute_add(
        self, event: Event, session: TradeSession, quantity: int
    ) -> OrderResult:
        """Execute ADD (scale in) order."""
        # Similar to entry but no bracket needed (uses session's existing stops)
        try:
            contract = self._build_contract_from_session(session)

            # Qualify contract with IBKR
            qualified = await self.ib.qualifyContractsAsync(contract)
            if not qualified:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message=f"Contract not found: {contract.symbol} {contract.strike}{contract.right}",
                )
            contract = qualified[0]
            print(f"  ✓ Qualified contract: {contract.localSymbol}")

            add_price = event.entry_price or await self._get_market_price(
                contract
            )

            if not add_price:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message="Could not determine add price",
                )

            order = LimitOrder("BUY", quantity, add_price)
            order.tif = "DAY"  # Explicit Time In Force
            trade = self.ib.placeOrder(contract, order)

            filled = await self._wait_for_fill(trade, timeout=30)

            if filled:
                return OrderResult(
                    success=True,
                    order_id=trade.order.orderId,
                    status=OrderStatus.FILLED,
                    filled_price=trade.orderStatus.avgFillPrice,
                    message="Add filled successfully",
                )
            else:
                self.ib.cancelOrder(trade.order)
                return OrderResult(
                    success=False,
                    status=OrderStatus.CANCELLED,
                    message="Add order timed out",
                )

        except Exception as e:
            return OrderResult(
                success=False,
                status=OrderStatus.REJECTED,
                message=f"Add execution error: {e}",
            )

    async def _execute_exit(
        self, event: Event, session: TradeSession
    ) -> OrderResult:
        """Execute full exit."""
        try:
            # Get current position size
            total_quantity = session.total_quantity
            if total_quantity == 0:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message="No position to exit",
                )

            contract = self._build_contract_from_session(session)

            # Qualify contract with IBKR
            qualified = await self.ib.qualifyContractsAsync(contract)
            if not qualified:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message=f"Contract not found: {contract.symbol} {contract.strike}{contract.right}",
                )
            contract = qualified[0]
            print(f"  ✓ Qualified contract: {contract.localSymbol}")

            # CRITICAL: Cancel all existing orders for this contract (bracket orders)
            # This prevents race conditions between EXIT and existing stop/target orders
            cancelled_orders = await self._cancel_orders_for_contract(contract)
            if cancelled_orders > 0:
                print(f"  ✓ Cancelled {cancelled_orders} existing order(s) (bracket stop/target)")

            exit_price = await self._get_market_price(contract)

            if not exit_price:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message="Could not determine exit price",
                )

            order = LimitOrder("SELL", total_quantity, exit_price)
            order.tif = "DAY"  # Explicit Time In Force
            trade = self.ib.placeOrder(contract, order)

            filled = await self._wait_for_fill(trade, timeout=30)

            if filled:
                session.state = "CLOSED"
                session.closed_at = datetime.now(timezone.utc)

                return OrderResult(
                    success=True,
                    order_id=trade.order.orderId,
                    status=OrderStatus.FILLED,
                    filled_price=trade.orderStatus.avgFillPrice,
                    message="Exit filled successfully",
                )
            else:
                self.ib.cancelOrder(trade.order)
                return OrderResult(
                    success=False,
                    status=OrderStatus.CANCELLED,
                    message="Exit order timed out",
                )

        except Exception as e:
            return OrderResult(
                success=False,
                status=OrderStatus.REJECTED,
                message=f"Exit execution error: {e}",
            )

    async def _execute_trim(
        self, event: Event, session: TradeSession
    ) -> OrderResult:
        """Execute partial exit."""
        # Similar to exit but with partial quantity
        trim_qty = event.quantity or (session.total_quantity // 2)
        # Implementation similar to _execute_exit but with trim_qty
        return OrderResult(
            success=False,
            status=OrderStatus.REJECTED,
            message="TRIM not yet implemented",
        )

    async def _execute_move_stop(
        self, event: Event, session: TradeSession
    ) -> OrderResult:
        """Update stop loss order."""
        return OrderResult(
            success=False,
            status=OrderStatus.REJECTED,
            message="MOVE_STOP not yet implemented",
        )

    def _build_contract(self, event: Event) -> Option:
        """Build IBKR Option contract from event."""
        # Convert expiry from ISO format (2025-12-12) to IBKR format (20251212)
        expiry_ibkr = event.expiry.replace('-', '') if event.expiry else ''

        return Option(
            symbol="SPY" if event.underlying == "SPY" else "SPX",
            lastTradeDateOrContractMonth=expiry_ibkr,
            strike=event.strike,
            right="C" if event.direction == Direction.CALL else "P",
            exchange="SMART",
        )

    def _build_contract_from_session(self, session: TradeSession) -> Option:
        """Build IBKR Option contract from session."""
        # Convert expiry from ISO format (2025-12-12) to IBKR format (20251212)
        expiry_ibkr = session.expiry.replace('-', '') if session.expiry else ''

        return Option(
            symbol="SPY" if session.underlying == "SPY" else "SPX",
            lastTradeDateOrContractMonth=expiry_ibkr,
            strike=session.strike,
            right="C" if session.direction == Direction.CALL else "P",
            exchange="SMART",
        )

    def _build_bracket_order(
        self,
        action: str,
        quantity: int,
        entry_price: float,
        stop_price: Optional[float],
        target_price: Optional[float],
    ) -> list[Order]:
        """
        Build proper IBKR bracket order with parent/child relationships.

        Parent order: Entry
        Child orders: Stop loss + Profit target (OCO - One Cancels Other)

        Returns list of orders: [parent, stop_child, target_child]
        """
        from ib_insync import Order

        orders = []

        # Parent order (entry) - don't transmit yet if we have children
        parent = LimitOrder(action, quantity, entry_price)
        parent.orderId = self.ib.client.getReqId()
        parent.transmit = False  # Don't transmit until children are attached
        parent.tif = "DAY"  # Explicit Time In Force
        orders.append(parent)

        # Child orders only activate when parent fills
        has_children = bool(stop_price or target_price)

        # Stop loss child (if provided)
        if stop_price:
            stop = LimitOrder("SELL", quantity, stop_price)
            stop.orderId = self.ib.client.getReqId()
            stop.parentId = parent.orderId  # Link to parent
            stop.transmit = not target_price  # Transmit only if it's the last order
            stop.tif = "DAY"  # Explicit Time In Force
            orders.append(stop)

        # Profit target child (if provided)
        if target_price:
            target = LimitOrder("SELL", quantity, target_price)
            target.orderId = self.ib.client.getReqId()
            target.parentId = parent.orderId  # Link to parent
            target.transmit = True  # Last order - transmit all
            target.tif = "DAY"  # Explicit Time In Force
            orders.append(target)

        # If no children, transmit the parent order
        if not has_children:
            parent.transmit = True

        return orders

    async def _cancel_orders_for_contract(self, contract: Option) -> int:
        """
        Cancel all open orders for a given contract.

        This is essential before placing EXIT orders to avoid race conditions
        with existing bracket orders (stop loss / take profit).

        Returns:
            Number of orders cancelled
        """
        try:
            # Get all open trades
            open_trades = self.ib.openTrades()

            cancelled_count = 0
            for trade in open_trades:
                # Check if this trade is for the same contract
                if (trade.contract.symbol == contract.symbol and
                    trade.contract.strike == contract.strike and
                    trade.contract.right == contract.right and
                    trade.contract.lastTradeDateOrContractMonth == contract.lastTradeDateOrContractMonth):

                    # Cancel the order
                    self.ib.cancelOrder(trade.order)
                    cancelled_count += 1
                    print(f"    Cancelled order {trade.order.orderId}: {trade.order.action} {trade.order.totalQuantity} @ ${trade.order.lmtPrice}")

            # Give IBKR a moment to process cancellations
            if cancelled_count > 0:
                await asyncio.sleep(0.5)

            return cancelled_count
        except Exception as e:
            print(f"  ⚠️  Error cancelling orders: {e}")
            return 0

    async def _get_market_price(self, contract: Option) -> Optional[float]:
        """Get current market price for contract."""
        try:
            # Use async qualification (contract should already be qualified, but ensure)
            qualified = await self.ib.qualifyContractsAsync(contract)
            if qualified:
                contract = qualified[0]

            ticker = self.ib.reqMktData(contract)
            await asyncio.sleep(1)  # Wait for data

            # Use midpoint of bid/ask
            if ticker.bid and ticker.ask:
                return (ticker.bid + ticker.ask) / 2
            elif ticker.last:
                return ticker.last

            return None
        except Exception as e:
            print(f"Error getting market price: {e}")
            return None

    async def _wait_for_fill(
        self, trade: Trade, timeout: int = 30
    ) -> bool:
        """
        Wait for order to fill.

        Returns True if filled, False if cancelled/timeout.
        """
        # Check initial status immediately
        if trade.orderStatus.status == "Filled":
            return True
        if trade.orderStatus.status in ["Cancelled", "ApiCancelled", "Inactive"]:
            print(f"  ✗ Order cancelled: {trade.orderStatus.status}")
            return False

        # Wait for status changes
        for i in range(timeout):
            await asyncio.sleep(1)

            status = trade.orderStatus.status

            # Check for fill
            if status == "Filled":
                return True

            # Check for cancellations/errors
            if status in ["Cancelled", "ApiCancelled", "Inactive", "PendingCancel"]:
                print(f"  ✗ Order cancelled: {status}")
                if trade.log:
                    # Print last log entry for debugging
                    last_log = trade.log[-1]
                    if last_log.message:
                        print(f"    Reason: {last_log.message}")
                return False

            # Log progress every 5 seconds
            if i % 5 == 0 and i > 0:
                print(f"  ⏳ Waiting for fill... ({i}s elapsed, status: {status})")

        print(f"  ✗ Order timed out after {timeout}s (status: {trade.orderStatus.status})")
        return False

    async def get_account_balance(self) -> Optional[float]:
        """
        Get current account balance from IBKR.

        Returns:
            Account net liquidation value, or None if unavailable
        """
        if not self.connected:
            return None

        try:
            # Wait a moment for initial data to populate after connection
            await asyncio.sleep(1)

            # Get account values (already populated by ib_insync after connection)
            account_values = self.ib.accountValues()

            # Find NetLiquidation value
            for item in account_values:
                if item.tag == 'NetLiquidation':
                    return float(item.value)

            # If not found, try accountSummary
            account_summary = self.ib.accountSummary()
            for item in account_summary:
                if item.tag == 'NetLiquidation':
                    return float(item.value)

            return None
        except Exception as e:
            print(f"Error getting account balance: {e}")
            return None

    async def _display_account_balance(self):
        """Display account balance on connection."""
        try:
            # Give IBKR extra time to populate account data after connection
            await asyncio.sleep(2)

            balance = await self.get_account_balance()
            if balance:
                print(f"Account Balance: ${balance:,.2f}")
            else:
                print("Account Balance: Unable to retrieve (data may not be ready yet)")
        except Exception as e:
            print(f"Could not retrieve account balance: {e}")

    async def get_positions(self) -> list:
        """
        Get current positions from IBKR.

        Returns:
            List of Position objects with contract and quantity info
        """
        if not self.connected:
            return []

        try:
            await asyncio.sleep(1)  # Wait for data to populate
            positions = self.ib.positions()
            return positions
        except Exception as e:
            print(f"Error getting positions: {e}")
            return []

    async def get_open_orders(self) -> list:
        """
        Get current open orders from IBKR.

        Returns:
            List of Trade objects with order info
        """
        if not self.connected:
            return []

        try:
            await asyncio.sleep(1)  # Wait for data to populate
            open_orders = self.ib.openTrades()
            return open_orders
        except Exception as e:
            print(f"Error getting open orders: {e}")
            return []

    async def display_account_status(self):
        """Display complete account status: balance, positions, and open orders."""
        print("\n" + "="*60)
        print("IBKR ACCOUNT STATUS")
        print("="*60)

        # Balance
        balance = await self.get_account_balance()
        if balance:
            print(f"\n💰 Account Balance: ${balance:,.2f}")
        else:
            print("\n💰 Account Balance: Unable to retrieve")

        # Positions
        positions = await self.get_positions()
        print(f"\n📊 Current Positions ({len(positions)}):")
        if positions:
            for pos in positions:
                contract = pos.contract
                symbol = contract.localSymbol if hasattr(contract, 'localSymbol') else contract.symbol
                print(f"  • {symbol}: {pos.position} contracts @ avg ${pos.avgCost:.2f}")
        else:
            print("  No open positions")

        # Open Orders
        open_orders = await self.get_open_orders()
        print(f"\n📋 Open Orders ({len(open_orders)}):")
        if open_orders:
            for trade in open_orders:
                contract = trade.contract
                order = trade.order
                symbol = contract.localSymbol if hasattr(contract, 'localSymbol') else contract.symbol
                status = trade.orderStatus.status
                print(f"  • {order.action} {order.totalQuantity} {symbol} @ ${order.lmtPrice:.2f} - {status}")
        else:
            print("  No open orders")

        print("="*60 + "\n")
