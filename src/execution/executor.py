import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel
from ib_insync import IB, Option, LimitOrder, Order, Trade

from ..models import Event, TradeSession, EventType, Direction, SessionState


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
        use_market_orders: bool = True,  # True = market orders, False = limit orders with 5¢ flexibility
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.use_market_orders = use_market_orders
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
                host=self.host, port=self.port, clientId=self.client_id, timeout=30
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

            # Configure market data and order strategy
            if self.use_market_orders:
                # IBKR Paper account or no real-time data: Use delayed data + market orders
                self.ib.reqMarketDataType(3)  # 3 = delayed data (free)
                print("📊 Order Strategy: MARKET orders (delayed data)")
            else:
                # IBKR Live account with real-time data: Use real-time data + limit orders
                self.ib.reqMarketDataType(1)  # 1 = real-time (subscription required)
                print("📊 Order Strategy: LIMIT orders with 5¢ flexibility (real-time data)")

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
        """
        Execute NEW entry with bracket orders based on ACTUAL fill price.

        Key improvements:
        1. Converts underlying targets to premium targets if needed
        2. Submits entry order ALONE (no brackets yet)
        3. Waits for fill, captures actual fill price
        4. Creates bracket orders using actual fill price
        5. Stores bracket percentages for future ADD operations
        """
        try:
            # Build option contract
            contract = self._build_contract(event)

            # CRITICAL: Qualify contract with IBKR to ensure it exists
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

            # Use the qualified contract
            contract = qualified[0]
            print(f"  ✓ Qualified contract: {contract.localSymbol}")

            # Convert underlying targets to premium if needed (Issue 5)
            target_price = event.targets[0] if event.targets else None
            if event.target_type == "UNDERLYING" and target_price:
                print(f"  ⓘ Converting underlying target to premium estimate...")

                # Get current underlying price
                current_underlying_price = await self._get_underlying_price(event.underlying)

                if current_underlying_price:
                    # Convert to premium estimate
                    premium_target = await self._convert_underlying_target_to_premium(
                        contract, target_price, current_underlying_price
                    )

                    if premium_target:
                        target_price = premium_target
                        print(f"  ✓ Using converted premium target: ${target_price:.2f}")
                    else:
                        print(f"  ⚠️ Conversion failed, using original target: ${target_price:.2f}")
                else:
                    print(f"  ⚠️ Could not fetch underlying price, using original target: ${target_price:.2f}")

            # Step 1: Submit entry order (Market or Limit based on data availability)
            from ib_insync import MarketOrder, LimitOrder

            if self.use_market_orders:
                # Use MARKET order (IBKR paper or no real-time data)
                parent_order = MarketOrder("BUY", quantity)
                parent_trade = self.ib.placeOrder(contract, parent_order)
                print(f"  ⓘ MARKET order submitted for {quantity} contracts")
            else:
                # Use LIMIT order with 5¢ flexibility (real-time data available)
                # Get current market data
                print(f"  Fetching current market data...")
                ticker = self.ib.reqMktData(contract)
                await asyncio.sleep(1)  # Wait for real-time data

                # Handle NaN and None values
                import math
                market_bid = ticker.bid if ticker.bid and not math.isnan(ticker.bid) else None
                market_ask = ticker.ask if ticker.ask and not math.isnan(ticker.ask) else None
                market_last = ticker.last if ticker.last and not math.isnan(ticker.last) else None

                if market_bid and market_ask:
                    print(f"  📊 Market: Bid ${market_bid:.2f} | Ask ${market_ask:.2f} | Last ${market_last:.2f if market_last else 0:.2f}")
                elif market_last:
                    print(f"  📊 Market: Last ${market_last:.2f}")

                # Determine entry price with 5-cent flexibility
                alert_price = event.entry_price or (market_ask if market_ask else market_last)

                if not alert_price:
                    print(f"  ⚠️ No market data available, falling back to MARKET order")
                    parent_order = MarketOrder("BUY", quantity)
                    parent_trade = self.ib.placeOrder(contract, parent_order)
                    print(f"  ⓘ MARKET order submitted (no market data)")
                else:
                    entry_price = alert_price
                    max_entry_price = alert_price + 0.05  # 5¢ flexibility

                    if market_ask:
                        if market_ask > entry_price and market_ask <= max_entry_price:
                            # Market moved up but within tolerance
                            old_price = entry_price
                            entry_price = market_ask
                            print(f"  ⓘ Adjusting entry: ${old_price:.2f} → ${entry_price:.2f} (market moved, within 5¢)")
                        elif market_ask > max_entry_price:
                            # Market moved too far, use max allowed
                            deviation = market_ask - alert_price
                            print(f"  ⚠️ Market ask ${market_ask:.2f} is ${deviation:.2f} above alert ${alert_price:.2f}")
                            print(f"  ⚠️ Using max allowed: ${max_entry_price:.2f} (alert + 5¢)")
                            entry_price = max_entry_price
                        elif market_ask < entry_price:
                            # Better entry available
                            old_price = entry_price
                            entry_price = market_ask
                            print(f"  ✓ Better entry: ${old_price:.2f} → ${entry_price:.2f} (below alert)")

                    parent_order = LimitOrder("BUY", quantity, entry_price)
                    parent_order.tif = "DAY"
                    parent_trade = self.ib.placeOrder(contract, parent_order)
                    print(f"  ⓘ LIMIT order submitted @ ${entry_price:.2f}")

            # Step 2: Wait for parent fill
            filled = await self._wait_for_fill(parent_trade, timeout=30)

            if not filled:
                self.ib.cancelOrder(parent_trade.order)
                return OrderResult(
                    success=False,
                    status=OrderStatus.CANCELLED,
                    message="Entry order timed out",
                )

            # Step 3: Capture ACTUAL fill price
            actual_fill_price = parent_trade.orderStatus.avgFillPrice
            print(f"  ✓ Entry filled at ${actual_fill_price:.2f}")

            # Step 4: Update session BEFORE creating brackets
            session.state = SessionState.OPEN
            session.opened_at = datetime.now(timezone.utc)
            session.entry_order_id = parent_trade.order.orderId
            session.total_quantity = quantity
            session.avg_entry_price = actual_fill_price

            # Step 5: Calculate bracket prices based on actual fill
            stop_price, final_target_price = self._calculate_bracket_prices(
                actual_fill_price,
                event.stop_loss,
                target_price,
            )

            # Step 6: Create bracket orders using actual fill price
            bracket_result = await self._create_bracket_orders(
                contract=contract,
                quantity=quantity,
                stop_price=stop_price,
                target_price=final_target_price,
                session=session,
            )

            # Step 7: Store bracket order IDs
            if bracket_result:
                session.stop_order_id = bracket_result.get('stop_order_id')
                session.target_order_ids = bracket_result.get('target_order_ids', [])
            else:
                # CRITICAL: Bracket creation failed, position is unprotected!
                print(f"  🚨 CRITICAL: Bracket creation FAILED after entry fill!")
                print(f"  🚨 Position is UNPROTECTED - initiating emergency exit")

                # Log critical error
                import traceback
                traceback.print_exc()

                # Attempt emergency market exit
                try:
                    from ib_insync import MarketOrder
                    emergency_order = MarketOrder("SELL", quantity)
                    emergency_trade = self.ib.placeOrder(contract, emergency_order)

                    # Wait for emergency exit (short timeout)
                    await asyncio.sleep(1)
                    filled = await self._wait_for_fill(emergency_trade, timeout=10)

                    if filled:
                        exit_price = emergency_trade.orderStatus.avgFillPrice
                        pnl = (exit_price - actual_fill_price) * quantity * 100

                        print(f"  ✓ Emergency exit filled @ ${exit_price:.2f} | P&L: ${pnl:+,.2f}")

                        # Close session
                        session.state = SessionState.CLOSED
                        session.closed_at = datetime.now(timezone.utc)
                        session.exit_reason = "BRACKET_FAILURE_EMERGENCY_EXIT"
                        session.exit_price = exit_price
                        session.total_quantity = 0
                        session.realized_pnl = pnl

                        return OrderResult(
                            success=False,
                            order_id=parent_trade.order.orderId,
                            status=OrderStatus.FILLED,
                            filled_price=actual_fill_price,
                            message=f"CRITICAL: Bracket failure. Emergency exit @ ${exit_price:.2f} | P&L: ${pnl:+,.2f}",
                        )
                    else:
                        print(f"  🚨 CRITICAL: Emergency exit FAILED - MANUAL INTERVENTION REQUIRED")
                        # Position still open but unprotected - user must manually close
                        session.state = SessionState.OPEN
                        return OrderResult(
                            success=False,
                            order_id=parent_trade.order.orderId,
                            status=OrderStatus.FILLED,
                            filled_price=actual_fill_price,
                            message=f"CRITICAL: Bracket failure. Emergency exit FAILED. CLOSE POSITION MANUALLY!",
                        )

                except Exception as emergency_error:
                    print(f"  🚨 CRITICAL: Emergency exit exception: {emergency_error}")
                    traceback.print_exc()
                    # Position still open but unprotected - user must manually close
                    session.state = SessionState.OPEN
                    return OrderResult(
                        success=False,
                        order_id=parent_trade.order.orderId,
                        status=OrderStatus.FILLED,
                        filled_price=actual_fill_price,
                        message=f"CRITICAL: Bracket failure. Emergency exit EXCEPTION. CLOSE POSITION MANUALLY!",
                    )

            # Step 8: Store bracket percentages for future ADD operations (Issue 4)
            # Validate fill price before calculating percentages
            if actual_fill_price <= 0:
                print(f"  ⚠️ WARNING: Invalid fill price {actual_fill_price}, cannot calculate bracket percentages")
                print(f"  ⚠️ ADD operations will not be able to update brackets")
                session.stop_loss_percent = None
                session.target_percent = None
            else:
                # Safe to calculate percentages
                if stop_price:
                    session.stop_loss_percent = ((stop_price - actual_fill_price) / actual_fill_price) * 100
                    # Validate extreme percentages (sanity check)
                    if session.stop_loss_percent < -99 or session.stop_loss_percent > 1000:
                        print(f"  ⚠️ WARNING: Extreme stop_loss_percent: {session.stop_loss_percent:.2f}%")

                if final_target_price:
                    session.target_percent = ((final_target_price - actual_fill_price) / actual_fill_price) * 100
                    # Validate extreme percentages (sanity check)
                    if session.target_percent < -99 or session.target_percent > 1000:
                        print(f"  ⚠️ WARNING: Extreme target_percent: {session.target_percent:.2f}%")

            # Build success message
            msg = f"Entry filled at ${actual_fill_price:.2f}"
            if stop_price or final_target_price:
                msg += " | Brackets:"
                if stop_price:
                    msg += f" Stop=${stop_price:.2f} ({session.stop_loss_percent:+.1f}%)"
                if final_target_price:
                    msg += f" Target=${final_target_price:.2f} ({session.target_percent:+.1f}%)"

            return OrderResult(
                success=True,
                order_id=parent_trade.order.orderId,
                status=OrderStatus.FILLED,
                filled_price=actual_fill_price,
                message=msg,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return OrderResult(
                success=False,
                status=OrderStatus.REJECTED,
                message=f"Execution error: {e}",
            )

    async def _execute_add(
        self, event: Event, session: TradeSession, quantity: int
    ) -> OrderResult:
        """
        Execute ADD (scale in) order with bracket updates.

        Process:
        1. Submit ADD order and wait for fill
        2. Calculate new weighted average entry price
        3. Update session quantities
        4. Recalculate and update brackets based on new average
        """
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

            # Submit ADD order (Market or Limit based on data availability)
            from ib_insync import MarketOrder, LimitOrder

            if self.use_market_orders:
                # Use MARKET order (IBKR paper or no real-time data)
                order = MarketOrder("BUY", quantity)
                trade = self.ib.placeOrder(contract, order)
                print(f"  ⓘ ADD MARKET order submitted: {quantity} contracts")
            else:
                # Use LIMIT order with 5¢ flexibility (real-time data available)
                print(f"  Fetching current market data...")
                ticker = self.ib.reqMktData(contract)
                await asyncio.sleep(1)

                import math
                market_ask = ticker.ask if ticker.ask and not math.isnan(ticker.ask) else None
                market_last = ticker.last if ticker.last and not math.isnan(ticker.last) else None

                add_price = event.entry_price or market_ask or market_last

                if not add_price:
                    print(f"  ⚠️ No market data, falling back to MARKET order")
                    order = MarketOrder("BUY", quantity)
                    trade = self.ib.placeOrder(contract, order)
                    print(f"  ⓘ ADD MARKET order submitted (no data)")
                else:
                    # Allow 5¢ flexibility
                    if market_ask and market_ask > add_price:
                        if market_ask <= add_price + 0.05:
                            print(f"  ⓘ Adjusting ADD: ${add_price:.2f} → ${market_ask:.2f} (within 5¢)")
                            add_price = market_ask
                        else:
                            print(f"  ⚠️ Using max allowed: ${add_price + 0.05:.2f}")
                            add_price = add_price + 0.05
                    elif market_ask and market_ask < add_price:
                        print(f"  ✓ Better ADD entry: ${add_price:.2f} → ${market_ask:.2f}")
                        add_price = market_ask

                    order = LimitOrder("BUY", quantity, add_price)
                    order.tif = "DAY"
                    trade = self.ib.placeOrder(contract, order)
                    print(f"  ⓘ ADD LIMIT order submitted @ ${add_price:.2f}")

            # Wait for fill
            filled = await self._wait_for_fill(trade, timeout=30)

            if not filled:
                self.ib.cancelOrder(trade.order)
                return OrderResult(
                    success=False,
                    status=OrderStatus.CANCELLED,
                    message="Add order timed out",
                )

            # Get actual fill price
            actual_add_price = trade.orderStatus.avgFillPrice

            # Calculate new average entry price (weighted average)
            old_quantity = session.total_quantity
            old_avg_price = session.avg_entry_price
            new_quantity = old_quantity + quantity

            # Validate before division
            if new_quantity <= 0:
                print(f"  🚨 ERROR: Invalid new_quantity {new_quantity} in ADD calculation")
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message=f"Invalid quantity calculation: old={old_quantity}, add={quantity}",
                )

            new_avg_price = ((old_avg_price * old_quantity) + (actual_add_price * quantity)) / new_quantity

            print(f"  ✓ ADD filled: {quantity} @ ${actual_add_price:.2f}")
            print(f"  Position: {old_quantity} @ ${old_avg_price:.2f} + {quantity} @ ${actual_add_price:.2f}")
            print(f"  New Average: {new_quantity} @ ${new_avg_price:.2f}")

            # Update session
            session.total_quantity = new_quantity
            session.avg_entry_price = new_avg_price
            session.num_adds += 1

            # Update brackets based on new average (Issue 4)
            await self._update_brackets_for_add(session, contract)

            return OrderResult(
                success=True,
                order_id=trade.order.orderId,
                status=OrderStatus.FILLED,
                filled_price=actual_add_price,
                message=f"Added {quantity} @ ${actual_add_price:.2f} | New Avg: ${new_avg_price:.2f} ({new_quantity} total)",
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
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

            # Use MARKET order for fast exit (speed more important than price)
            from ib_insync import MarketOrder
            order = MarketOrder("SELL", total_quantity)
            trade = self.ib.placeOrder(contract, order)

            print(f"  ⓘ EXIT MARKET order submitted for {total_quantity} contracts")

            filled = await self._wait_for_fill(trade, timeout=30)

            if filled:
                session.state = SessionState.CLOSED
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
        """
        Execute partial exit (TRIM).

        Handles:
        - Specific quantity: "trim 5 contracts"
        - Percentage: "took off half" (50%)
        - Auto-closes session if trim reduces position to 0
        - Updates brackets for remaining position
        """
        try:
            # Get current position size
            current_quantity = session.total_quantity
            if current_quantity == 0:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message="No position to trim",
                )

            # Calculate trim quantity
            trim_qty = self._calculate_trim_quantity(event, session)

            if trim_qty <= 0 or trim_qty > current_quantity:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message=f"Invalid trim quantity: {trim_qty} (position: {current_quantity})",
                )

            # Build contract
            contract = self._build_contract_from_session(session)
            qualified = await self.ib.qualifyContractsAsync(contract)

            if not qualified:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message=f"Contract not found: {contract.symbol} {contract.strike}{contract.right}",
                )

            contract = qualified[0]
            print(f"  ✓ Qualified contract: {contract.localSymbol}")

            # Use MARKET order for fast exit (speed more important than price)
            from ib_insync import MarketOrder
            order = MarketOrder("SELL", trim_qty)
            trade = self.ib.placeOrder(contract, order)

            print(f"  ⓘ TRIM MARKET order submitted: {trim_qty} contracts")

            # Wait for fill
            filled = await self._wait_for_fill(trade, timeout=30)

            if not filled:
                self.ib.cancelOrder(trade.order)
                return OrderResult(
                    success=False,
                    status=OrderStatus.CANCELLED,
                    message="Trim order timed out",
                )

            fill_price = trade.orderStatus.avgFillPrice

            # Calculate P&L for trimmed portion
            trim_pnl = (fill_price - session.avg_entry_price) * trim_qty * 100

            # Update session
            session.total_quantity -= trim_qty
            session.realized_pnl += trim_pnl

            # Check if position is fully closed
            if session.total_quantity == 0:
                print(f"  ⓘ TRIM reduced position to 0, auto-closing session")

                session.state = SessionState.CLOSED
                session.closed_at = datetime.now(timezone.utc)
                session.exit_reason = "TRIM_TO_ZERO"
                session.exit_price = fill_price

                # Cancel remaining brackets
                if session.stop_order_id or session.target_order_ids:
                    order_ids = []
                    if session.stop_order_id:
                        order_ids.append(session.stop_order_id)
                    if session.target_order_ids:
                        order_ids.extend(session.target_order_ids)
                    await self._cancel_sibling_orders(order_ids)

                return OrderResult(
                    success=True,
                    order_id=trade.order.orderId,
                    status=OrderStatus.FILLED,
                    filled_price=fill_price,
                    message=f"Trimmed {trim_qty} @ ${fill_price:.2f} | P&L: ${trim_pnl:+,.2f} | Session CLOSED",
                )
            else:
                # Position still open, update brackets
                print(f"  ⓘ Position trimmed: {current_quantity} → {session.total_quantity}")

                # Update brackets for reduced position
                await self._update_brackets_for_trim(session, contract)

                return OrderResult(
                    success=True,
                    order_id=trade.order.orderId,
                    status=OrderStatus.FILLED,
                    filled_price=fill_price,
                    message=f"Trimmed {trim_qty} @ ${fill_price:.2f} | P&L: ${trim_pnl:+,.2f} | Remaining: {session.total_quantity}",
                )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return OrderResult(
                success=False,
                status=OrderStatus.REJECTED,
                message=f"Trim execution error: {e}",
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

        # Map underlying to IBKR symbol (SPY and QQQ only)
        if event.underlying in ["SPY", "QQQ"]:
            symbol = event.underlying
        else:
            symbol = event.underlying  # Fallback to raw value

        return Option(
            symbol=symbol,
            lastTradeDateOrContractMonth=expiry_ibkr,
            strike=event.strike,
            right="C" if event.direction == Direction.CALL else "P",
            exchange="SMART",
        )

    def _build_contract_from_session(self, session: TradeSession) -> Option:
        """Build IBKR Option contract from session."""
        # Convert expiry from ISO format (2025-12-12) to IBKR format (20251212)
        expiry_ibkr = session.expiry.replace('-', '') if session.expiry else ''

        # Map underlying to IBKR symbol (SPY and QQQ only)
        if session.underlying in ["SPY", "QQQ"]:
            symbol = session.underlying
        else:
            symbol = session.underlying  # Fallback to raw value

        return Option(
            symbol=symbol,
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

    def _calculate_bracket_prices(
        self,
        actual_fill_price: float,
        original_stop: Optional[float],
        original_target: Optional[float],
    ) -> tuple[Optional[float], Optional[float]]:
        """
        Calculate bracket prices based on actual fill price.

        Priority:
        1. Use Discord alert stop/target if provided
        2. Otherwise calculate from fill price using config percentages

        Args:
            actual_fill_price: Actual fill price from parent order
            original_stop: Original stop price from Discord (or None)
            original_target: Original target price from Discord (or None)

        Returns:
            (stop_price, target_price) tuple
        """
        # Use Discord prices if provided
        stop_price = original_stop
        target_price = original_target

        # Calculate from fill price if not provided
        if not stop_price:
            # Default: 25% stop loss from fill price
            stop_percent = 25.0  # This should come from config
            stop_price = actual_fill_price * (1 - stop_percent / 100)
            print(f"  ⓘ Auto stop-loss: ${stop_price:.2f} ({stop_percent}% below fill)")

        if not target_price:
            # Default: 2:1 risk/reward ratio
            risk = actual_fill_price - stop_price
            target_price = actual_fill_price + (risk * 2.0)
            print(f"  ⓘ Auto target: ${target_price:.2f} (2:1 R/R)")

        # Round to 2 decimals for option premiums
        if stop_price:
            stop_price = round(stop_price, 2)
        if target_price:
            target_price = round(target_price, 2)

        return stop_price, target_price

    async def _create_bracket_orders(
        self,
        contract: Option,
        quantity: int,
        stop_price: Optional[float],
        target_price: Optional[float],
        session: TradeSession,
    ) -> Optional[dict]:
        """
        Create independent stop and target orders (not parent-child linked).

        These are standalone orders created AFTER entry fills.
        They act as OCO (One Cancels Other) through our monitoring callbacks.

        Args:
            contract: Qualified option contract
            quantity: Number of contracts
            stop_price: Stop loss price
            target_price: Take profit price
            session: Trade session to update with order IDs

        Returns:
            Dictionary with 'stop_order_id' and 'target_order_ids' keys, or None on error
        """
        order_ids = {}

        try:
            # Create stop loss order
            if stop_price:
                stop_order = LimitOrder("SELL", quantity, stop_price)
                stop_order.tif = "DAY"
                stop_trade = self.ib.placeOrder(contract, stop_order)
                await asyncio.sleep(0.2)  # Small delay for order submission
                order_ids['stop_order_id'] = stop_trade.order.orderId
                print(f"  ✓ Stop order created: ${stop_price:.2f} (Order #{stop_trade.order.orderId})")

            # Create target order
            if target_price:
                target_order = LimitOrder("SELL", quantity, target_price)
                target_order.tif = "DAY"
                target_trade = self.ib.placeOrder(contract, target_order)
                await asyncio.sleep(0.2)
                order_ids['target_order_ids'] = [target_trade.order.orderId]
                print(f"  ✓ Target order created: ${target_price:.2f} (Order #{target_trade.order.orderId})")

            return order_ids

        except Exception as e:
            print(f"  ⚠️ Failed to create bracket orders: {e}")
            return None

    def _calculate_trim_quantity(self, event: Event, session: TradeSession) -> int:
        """
        Calculate trim quantity from event.

        Supports:
        - Explicit quantity: event.quantity = 5
        - Percentage: "half" = 50%, "third" = 33%

        Args:
            event: TRIM event
            session: Current session

        Returns:
            Number of contracts to trim
        """
        current_qty = session.total_quantity

        # If explicit quantity provided
        if event.quantity and event.quantity > 0:
            return event.quantity

        # If percentage in risk_notes (e.g., "took off half")
        if event.risk_notes:
            notes_lower = event.risk_notes.lower()

            if "half" in notes_lower or "50%" in notes_lower:
                return max(1, int(current_qty * 0.5))
            elif "third" in notes_lower or "33%" in notes_lower:
                return max(1, int(current_qty * 0.33))
            elif "quarter" in notes_lower or "25%" in notes_lower:
                return max(1, int(current_qty * 0.25))
            elif "all" in notes_lower or "full" in notes_lower or "100%" in notes_lower:
                return current_qty

        # Default: trim half (ensure at least 1 contract)
        return max(1, int(current_qty * 0.5))

    async def _update_brackets_for_trim(self, session: TradeSession, contract: Option):
        """
        Update bracket orders after TRIM to reflect new position size.

        Strategy:
        - Cancel old brackets (old quantity)
        - Create new brackets (new quantity, same prices)
        """
        try:
            # Check session state to prevent race condition with position reconciliation
            if session.state != SessionState.OPEN:
                print(f"    ⚠️ Skipping bracket update - session is {session.state.value}, not OPEN")
                return

            # Cancel existing brackets
            print(f"    Updating brackets after TRIM...")

            order_ids_to_cancel = []
            if session.stop_order_id:
                order_ids_to_cancel.append(session.stop_order_id)
            if session.target_order_ids:
                order_ids_to_cancel.extend(session.target_order_ids)

            if order_ids_to_cancel:
                await self._cancel_sibling_orders(order_ids_to_cancel)
                print(f"    ✓ Cancelled {len(order_ids_to_cancel)} old bracket order(s)")

            # Calculate bracket prices using stored percentages
            new_stop = None
            new_target = None

            if session.stop_loss_percent is not None:
                new_stop = session.avg_entry_price * (1 + session.stop_loss_percent / 100)
                new_stop = round(new_stop, 2)

            if session.target_percent is not None:
                new_target = session.avg_entry_price * (1 + session.target_percent / 100)
                new_target = round(new_target, 2)

            # Create new brackets with updated quantity
            if new_stop or new_target:
                bracket_result = await self._create_bracket_orders(
                    contract=contract,
                    quantity=session.total_quantity,  # Use NEW reduced quantity
                    stop_price=new_stop,
                    target_price=new_target,
                    session=session,
                )

                # Update session with new bracket IDs
                if bracket_result:
                    session.stop_order_id = bracket_result.get('stop_order_id')
                    session.target_order_ids = bracket_result.get('target_order_ids', [])
                    print(f"    ✓ New brackets created for {session.total_quantity} contracts")

        except Exception as e:
            print(f"    ⚠️ Failed to update brackets after TRIM: {e}")
            print(f"    ⚠️ Position may be unprotected - manual monitoring required!")

    async def _update_brackets_for_add(self, session: TradeSession, contract: Option):
        """
        Update bracket orders after ADD based on new average entry price.

        Uses percentage-based recalculation:
        - If stop was -10% from old avg, make it -10% from new avg
        - Same for target

        Process:
        1. Cancel old brackets
        2. Calculate new bracket prices using stored percentages
        3. Create new brackets with updated quantity and prices
        """
        try:
            # Check session state to prevent race condition with position reconciliation
            if session.state != SessionState.OPEN:
                print(f"    ⚠️ Skipping bracket update - session is {session.state.value}, not OPEN")
                return

            # Cancel old brackets
            print(f"    Updating brackets for new average...")

            order_ids_to_cancel = []
            if session.stop_order_id:
                order_ids_to_cancel.append(session.stop_order_id)
            if session.target_order_ids:
                order_ids_to_cancel.extend(session.target_order_ids)

            if order_ids_to_cancel:
                await self._cancel_sibling_orders(order_ids_to_cancel)
                print(f"    ✓ Cancelled {len(order_ids_to_cancel)} old bracket order(s)")

            # Calculate new bracket prices using percentages
            new_avg = session.avg_entry_price
            new_stop = None
            new_target = None

            if session.stop_loss_percent is not None:
                # Apply same percentage offset to new average
                new_stop = new_avg * (1 + session.stop_loss_percent / 100)
                new_stop = round(new_stop, 2)
                print(f"    New Stop: ${new_stop:.2f} ({session.stop_loss_percent:+.1f}% from avg)")

            if session.target_percent is not None:
                new_target = new_avg * (1 + session.target_percent / 100)
                new_target = round(new_target, 2)
                print(f"    New Target: ${new_target:.2f} ({session.target_percent:+.1f}% from avg)")

            # Create new brackets with updated quantity and prices
            if new_stop or new_target:
                bracket_result = await self._create_bracket_orders(
                    contract=contract,
                    quantity=session.total_quantity,  # Use NEW total quantity
                    stop_price=new_stop,
                    target_price=new_target,
                    session=session,
                )

                # Update session with new bracket IDs
                if bracket_result:
                    session.stop_order_id = bracket_result.get('stop_order_id')
                    session.target_order_ids = bracket_result.get('target_order_ids', [])
                    print(f"    ✓ New brackets created for {session.total_quantity} contracts")
            else:
                print(f"    ⓘ No bracket percentages stored, skipping bracket update")

        except Exception as e:
            print(f"    ⚠️ Failed to update brackets after ADD: {e}")
            print(f"    ⚠️ Position may be unprotected - manual monitoring required!")

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
            import math

            # Use async qualification (contract should already be qualified, but ensure)
            qualified = await self.ib.qualifyContractsAsync(contract)
            if qualified:
                contract = qualified[0]

            ticker = self.ib.reqMktData(contract)
            await asyncio.sleep(2)  # Wait for data (longer for delayed data)

            # Clean NaN values
            bid = ticker.bid if ticker.bid and not math.isnan(ticker.bid) else None
            ask = ticker.ask if ticker.ask and not math.isnan(ticker.ask) else None
            last = ticker.last if ticker.last and not math.isnan(ticker.last) else None

            # Use midpoint of bid/ask
            if bid and ask:
                return (bid + ask) / 2
            elif last:
                return last

            return None
        except Exception as e:
            print(f"Error getting market price: {e}")
            return None

    async def _get_underlying_price(self, underlying_symbol: str) -> Optional[float]:
        """
        Get current stock price for underlying asset.

        Args:
            underlying_symbol: Stock symbol (SPY or QQQ)

        Returns:
            Current stock price or None on error
        """
        try:
            from ib_insync import Stock

            # Create stock contract
            stock = Stock(symbol=underlying_symbol, exchange="SMART", currency="USD")

            # Qualify contract
            qualified = await self.ib.qualifyContractsAsync(stock)
            if not qualified:
                print(f"  ⚠️ Could not qualify stock contract for {underlying_symbol}")
                return None

            stock = qualified[0]

            # Get market data
            import math
            ticker = self.ib.reqMktData(stock)
            await asyncio.sleep(2)  # Wait for data (longer for delayed data)

            # Clean NaN values
            last = ticker.last if ticker.last and not math.isnan(ticker.last) else None
            bid = ticker.bid if ticker.bid and not math.isnan(ticker.bid) else None
            ask = ticker.ask if ticker.ask and not math.isnan(ticker.ask) else None

            # Use last price or midpoint
            if last:
                return last
            elif bid and ask:
                return (bid + ask) / 2

            return None

        except Exception as e:
            print(f"  ⚠️ Failed to get underlying price for {underlying_symbol}: {e}")
            return None

    async def _convert_underlying_target_to_premium(
        self,
        contract: Option,
        underlying_target: float,
        current_underlying_price: float,
    ) -> Optional[float]:
        """
        Convert underlying price target to option premium target.

        Uses intrinsic value method:
        - For CALL: intrinsic = max(0, underlying_target - strike)
        - For PUT: intrinsic = max(0, strike - underlying_target)

        Then adds time value estimate based on current premium.

        Args:
            contract: Option contract
            underlying_target: Target stock price (e.g., 600.0 for QQQ)
            current_underlying_price: Current stock price

        Returns:
            Estimated option premium at underlying_target price, or None on error
        """
        try:
            # Get current option premium
            current_premium = await self._get_market_price(contract)
            if not current_premium or current_premium <= 0:
                print(f"  ⚠️ Could not get current premium for target conversion")
                return None

            strike = contract.strike
            is_call = contract.right == "C"

            # Calculate current intrinsic value
            if is_call:
                current_intrinsic = max(0, current_underlying_price - strike)
                target_intrinsic = max(0, underlying_target - strike)
            else:  # PUT
                current_intrinsic = max(0, strike - current_underlying_price)
                target_intrinsic = max(0, strike - underlying_target)

            # Estimate time value (extrinsic)
            current_time_value = max(0, current_premium - current_intrinsic)

            # For 0DTE options, time value decays quickly
            # Assume 50% time value retention as underlying moves to target
            estimated_premium = target_intrinsic + (current_time_value * 0.5)

            # Round to 2 decimals
            estimated_premium = round(estimated_premium, 2)

            # Sanity check: premium should be positive and reasonable
            if estimated_premium <= 0:
                print(f"  ⚠️ Invalid premium estimate: ${estimated_premium:.2f}")
                return None

            print(f"  ⓘ Underlying target ${underlying_target:.2f} → Premium estimate ${estimated_premium:.2f}")
            print(f"     (Current: ${current_underlying_price:.2f} underlying, ${current_premium:.2f} premium)")

            return estimated_premium

        except Exception as e:
            print(f"  ⚠️ Failed to convert underlying target: {e}")
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
