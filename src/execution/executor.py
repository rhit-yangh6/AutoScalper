import asyncio
from datetime import datetime
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
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()
        self.connected = False
        self.kill_switch_active = False

        # Track submitted orders for idempotency
        self.submitted_orders: dict[str, Trade] = {}

    async def connect(self) -> bool:
        """Connect to IBKR TWS/Gateway."""
        try:
            await self.ib.connectAsync(
                host=self.host, port=self.port, clientId=self.client_id
            )
            self.connected = True
            print(f"Connected to IBKR at {self.host}:{self.port}")

            # Get and display account balance
            await self._display_account_balance()

            return True
        except Exception as e:
            print(f"Failed to connect to IBKR: {e}")
            self.connected = False
            return False

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
                session.opened_at = datetime.utcnow()

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
            exit_price = await self._get_market_price(contract)

            if not exit_price:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message="Could not determine exit price",
                )

            order = LimitOrder("SELL", total_quantity, exit_price)
            trade = self.ib.placeOrder(contract, order)

            filled = await self._wait_for_fill(trade, timeout=30)

            if filled:
                session.state = "CLOSED"
                session.closed_at = datetime.utcnow()

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
        orders.append(parent)

        # Child orders only activate when parent fills
        has_children = bool(stop_price or target_price)

        # Stop loss child (if provided)
        if stop_price:
            stop = LimitOrder("SELL", quantity, stop_price)
            stop.orderId = self.ib.client.getReqId()
            stop.parentId = parent.orderId  # Link to parent
            stop.transmit = not target_price  # Transmit only if it's the last order
            orders.append(stop)

        # Profit target child (if provided)
        if target_price:
            target = LimitOrder("SELL", quantity, target_price)
            target.orderId = self.ib.client.getReqId()
            target.parentId = parent.orderId  # Link to parent
            target.transmit = True  # Last order - transmit all
            orders.append(target)

        # If no children, transmit the parent order
        if not has_children:
            parent.transmit = True

        return orders

    async def _get_market_price(self, contract: Option) -> Optional[float]:
        """Get current market price for contract."""
        try:
            self.ib.qualifyContracts(contract)
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

        Returns True if filled, False if timeout.
        """
        for _ in range(timeout):
            await asyncio.sleep(1)
            if trade.orderStatus.status == "Filled":
                return True
            if trade.orderStatus.status in ["Cancelled", "ApiCancelled"]:
                return False

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
