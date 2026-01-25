"""
MNQ Futures Execution Engine

Handles order execution via Interactive Brokers for MNQ micro futures.
Supports both LONG and SHORT positions. No bracket orders - exits via TradingView signals.
"""

import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel
from ib_insync import IB, Future, MarketOrder, Trade

from ..models import Event, TradeSession, EventType, PositionSide, SessionState


# MNQ contract specifications
MNQ_TICK_SIZE = 0.25
MNQ_POINT_VALUE = 2.0  # $2 per point for MNQ


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
    Handles MNQ futures order execution via Interactive Brokers.

    Simple execution model:
    - MARKET orders for entry (NEW signal)
    - MARKET orders for exit (EXIT signal from TradingView)
    - No bracket orders - positions are naked
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4002,
        client_id: int = 1,
        session_manager=None,
        config: dict = None,
        notifier=None,
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.config = config or {}
        self.notifier = notifier
        self.ib = IB()
        self.connected = False
        self.kill_switch_active = False
        self.session_manager = session_manager
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 999999

    async def connect(self) -> bool:
        """Connect to IBKR TWS/Gateway."""
        try:
            await self.ib.connectAsync(
                host=self.host, port=self.port, clientId=self.client_id, timeout=30
            )
            self.connected = True
            self.reconnect_attempts = 0

            self.ib.disconnectedEvent += self._on_disconnected

            print(f"Connected to IBKR at {self.host}:{self.port}")
            print("Auto-reconnection enabled")

            # Use delayed data (free) for paper trading
            self.ib.reqMarketDataType(3)
            print("Using delayed market data")

            await self._display_account_balance()

            return True
        except Exception as e:
            print(f"Failed to connect to IBKR: {e}")
            self.connected = False
            return False

    async def _display_account_balance(self):
        """Display current account balance."""
        try:
            account_values = self.ib.accountSummary()
            for av in account_values:
                if av.tag == "NetLiquidation":
                    print(f"Account Balance: ${float(av.value):,.2f}")
                    break
        except Exception as e:
            print(f"Could not get account balance: {e}")

    def _on_disconnected(self):
        """Callback when IBKR connection is lost."""
        self.connected = False
        print("IBKR connection lost! Auto-reconnection will attempt...")

    async def reconnect(self) -> bool:
        """Attempt to reconnect to IBKR."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            print(f"Max reconnection attempts reached.")
            return False

        self.reconnect_attempts += 1
        print(f"Reconnection attempt {self.reconnect_attempts}...")

        wait_time = min(2 ** min(self.reconnect_attempts, 6), 60)
        await asyncio.sleep(wait_time)

        try:
            success = await self.connect()
            if success:
                print(f"Reconnected to IBKR successfully!")
                return True
            return False
        except Exception as e:
            print(f"Reconnection attempt failed: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from IBKR."""
        if self.connected:
            self.ib.disconnect()
            self.connected = False
            print("Disconnected from IBKR")

    def activate_kill_switch(self, reason: str) -> None:
        """Activate kill switch - blocks all new orders."""
        self.kill_switch_active = True
        print(f"KILL SWITCH ACTIVATED: {reason}")

    def deactivate_kill_switch(self) -> None:
        """Deactivate kill switch."""
        self.kill_switch_active = False
        print("Kill switch deactivated")

    def _calculate_session_pnl(self, session: TradeSession, exit_price: float) -> float:
        """
        Calculate realized P&L for a futures session.

        For MNQ: P&L = (Exit - Entry) * Quantity * Point Value * Direction
        Point Value = $2 per point for MNQ
        """
        if session.total_quantity == 0:
            return 0.0

        direction = 1 if session.position_side == PositionSide.LONG else -1
        price_diff = exit_price - session.avg_entry_price
        pnl = price_diff * session.total_quantity * MNQ_POINT_VALUE * direction

        return round(pnl, 2)

    async def execute_event(
        self,
        event: Event,
        session: TradeSession,
        quantity: int,
    ) -> OrderResult:
        """Execute an event based on its type."""
        if self.kill_switch_active:
            return OrderResult(
                success=False,
                status=OrderStatus.REJECTED,
                message="Kill switch is active",
            )

        if not self.connected:
            return OrderResult(
                success=False,
                status=OrderStatus.REJECTED,
                message="Not connected to IBKR",
            )

        if event.event_type == EventType.NEW:
            return await self._execute_entry(event, session, quantity)
        elif event.event_type == EventType.ADD:
            return await self._execute_add(event, session, quantity)
        elif event.event_type in [EventType.EXIT, EventType.CLOSE_ALL]:
            return await self._execute_exit(event, session)
        else:
            return OrderResult(
                success=False,
                status=OrderStatus.REJECTED,
                message=f"Event type {event.event_type} not executable",
            )

    def _build_contract(self, symbol: str = "MNQ") -> Future:
        """Build MNQ futures contract (continuous)."""
        return Future(
            symbol=symbol,
            exchange="CME",
            currency="USD"
        )

    def _get_entry_exit_actions(self, position_side: PositionSide) -> tuple[str, str]:
        """Get entry and exit order actions based on position side."""
        if position_side == PositionSide.LONG:
            return "BUY", "SELL"
        else:  # SHORT
            return "SELL", "BUY"

    async def _execute_entry(
        self, event: Event, session: TradeSession, quantity: int
    ) -> OrderResult:
        """
        Execute NEW entry - naked position, no brackets.

        For LONG: BUY
        For SHORT: SELL
        """
        try:
            contract = self._build_contract(event.symbol)
            qualified = await self.ib.qualifyContractsAsync(contract)

            if not qualified:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message=f"Contract not found: {event.symbol}",
                )

            contract = qualified[0]
            print(f"  Contract: {contract.localSymbol}")

            entry_action, _ = self._get_entry_exit_actions(event.position_side)

            # MARKET order for immediate fill
            order = MarketOrder(entry_action, quantity)
            trade = self.ib.placeOrder(contract, order)

            print(f"  {entry_action} MARKET x{quantity} submitted")

            filled = await self._wait_for_fill(trade, timeout=30)

            if not filled:
                self.ib.cancelOrder(trade.order)
                session.state = SessionState.CLOSED
                session.closed_at = datetime.now(timezone.utc)
                session.exit_reason = "ENTRY_TIMEOUT"

                return OrderResult(
                    success=False,
                    status=OrderStatus.CANCELLED,
                    message="Entry order timed out",
                )

            fill_price = trade.orderStatus.avgFillPrice
            print(f"  Filled @ ${fill_price:.2f}")

            # Update session
            now = datetime.now(timezone.utc)
            session.state = SessionState.OPEN
            session.opened_at = now
            session.updated_at = now
            session.entry_order_id = trade.order.orderId
            session.total_quantity = quantity
            session.avg_entry_price = fill_price

            return OrderResult(
                success=True,
                order_id=trade.order.orderId,
                status=OrderStatus.FILLED,
                filled_price=fill_price,
                message=f"Entry filled @ ${fill_price:.2f}",
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
        """Execute ADD (scale in) order."""
        try:
            if quantity <= 0:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message=f"Cannot ADD {quantity} contracts",
                )

            contract = self._build_contract(session.symbol)
            qualified = await self.ib.qualifyContractsAsync(contract)

            if not qualified:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message=f"Contract not found: {session.symbol}",
                )

            contract = qualified[0]
            entry_action, _ = self._get_entry_exit_actions(session.position_side)

            order = MarketOrder(entry_action, quantity)
            trade = self.ib.placeOrder(contract, order)

            print(f"  ADD {entry_action} MARKET x{quantity} submitted")

            filled = await self._wait_for_fill(trade, timeout=30)

            if not filled:
                self.ib.cancelOrder(trade.order)
                return OrderResult(
                    success=False,
                    status=OrderStatus.CANCELLED,
                    message="Add order timed out",
                )

            add_price = trade.orderStatus.avgFillPrice

            # Calculate new weighted average
            old_qty = session.total_quantity
            old_avg = session.avg_entry_price
            new_qty = old_qty + quantity
            new_avg = ((old_avg * old_qty) + (add_price * quantity)) / new_qty

            print(f"  ADD filled @ ${add_price:.2f}")
            print(f"  New position: {new_qty} @ ${new_avg:.2f}")

            session.total_quantity = new_qty
            session.avg_entry_price = new_avg
            session.updated_at = datetime.now(timezone.utc)

            return OrderResult(
                success=True,
                order_id=trade.order.orderId,
                status=OrderStatus.FILLED,
                filled_price=add_price,
                message=f"Added {quantity} @ ${add_price:.2f} | Total: {new_qty} @ ${new_avg:.2f}",
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
            total_qty = session.total_quantity

            if total_qty == 0:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message="No position to exit",
                )

            contract = self._build_contract(session.symbol)
            qualified = await self.ib.qualifyContractsAsync(contract)

            if not qualified:
                return OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message=f"Contract not found: {session.symbol}",
                )

            contract = qualified[0]
            _, exit_action = self._get_entry_exit_actions(session.position_side)

            order = MarketOrder(exit_action, total_qty)
            trade = self.ib.placeOrder(contract, order)

            print(f"  EXIT {exit_action} MARKET x{total_qty} submitted")

            filled = await self._wait_for_fill(trade, timeout=30)

            if filled:
                fill_price = trade.orderStatus.avgFillPrice
                pnl = self._calculate_session_pnl(session, fill_price)

                now = datetime.now(timezone.utc)
                session.state = SessionState.CLOSED
                session.closed_at = now
                session.updated_at = now
                session.exit_reason = "SIGNAL_EXIT"
                session.exit_price = fill_price
                session.realized_pnl = pnl

                print(f"  Exit filled @ ${fill_price:.2f} | P&L: ${pnl:+,.2f}")

                return OrderResult(
                    success=True,
                    order_id=trade.order.orderId,
                    status=OrderStatus.FILLED,
                    filled_price=fill_price,
                    message=f"Exit @ ${fill_price:.2f} | P&L: ${pnl:+,.2f}",
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

    async def _wait_for_fill(self, trade: Trade, timeout: int = 30) -> bool:
        """Wait for order to fill with timeout."""
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            if trade.orderStatus.status == "Filled":
                return True
            if trade.orderStatus.status in ["Cancelled", "ApiCancelled"]:
                return False
            await asyncio.sleep(0.5)

        return trade.orderStatus.status == "Filled"

    async def get_positions(self) -> list:
        """Get all open positions."""
        return self.ib.positions()

    async def get_open_orders(self) -> list:
        """Get all open orders."""
        return [t for t in self.ib.trades() if t.isActive()]

    async def get_account_balance(self) -> Optional[float]:
        """Get current account balance."""
        try:
            account_values = self.ib.accountSummary()
            for av in account_values:
                if av.tag == "NetLiquidation":
                    return float(av.value)
        except:
            pass
        return None

    async def get_margin_requirement(self, symbol: str = "MNQ") -> Optional[float]:
        """
        Get initial margin requirement per contract from IBKR.

        Uses whatIfOrder to simulate a 1-contract order and get margin impact.
        Returns the initial margin required per contract.
        """
        try:
            contract = self._build_contract(symbol)
            qualified = await self.ib.qualifyContractsAsync(contract)

            if not qualified:
                print(f"Could not qualify contract for margin check: {symbol}")
                return None

            contract = qualified[0]

            # Simulate a 1-contract BUY order to get margin requirement
            order = MarketOrder("BUY", 1)
            order.whatIf = True

            # whatIfOrder returns OrderState with margin info
            order_state = await self.ib.whatIfOrderAsync(contract, order)

            if order_state:
                # initMarginChange is the margin required for this order
                init_margin = float(order_state.initMarginChange)
                print(f"IBKR Margin for {symbol}: ${init_margin:,.2f} per contract")
                return init_margin
            else:
                print(f"Could not get margin info for {symbol}")
                return None

        except Exception as e:
            print(f"Error fetching margin requirement: {e}")
            return None

    async def get_futures_price(self, symbol: str = "MNQ") -> Optional[float]:
        """
        Get current futures price from IBKR.

        Returns the last traded price or mid-point if available.
        """
        try:
            contract = self._build_contract(symbol)
            qualified = await self.ib.qualifyContractsAsync(contract)

            if not qualified:
                return None

            contract = qualified[0]

            # Request market data
            self.ib.reqMktData(contract, '', False, False)
            await asyncio.sleep(2)  # Wait for data

            ticker = self.ib.ticker(contract)

            if ticker:
                # Prefer last price, then mid, then close
                if ticker.last and ticker.last > 0:
                    return ticker.last
                elif ticker.bid and ticker.ask:
                    return (ticker.bid + ticker.ask) / 2
                elif ticker.close:
                    return ticker.close

            return None

        except Exception as e:
            print(f"Error fetching futures price: {e}")
            return None

    async def close_all_positions(self) -> list[OrderResult]:
        """Emergency: Close all open positions."""
        results = []
        positions = self.ib.positions()

        for pos in positions:
            if pos.position != 0:
                try:
                    action = "SELL" if pos.position > 0 else "BUY"
                    qty = abs(int(pos.position))
                    order = MarketOrder(action, qty)
                    trade = self.ib.placeOrder(pos.contract, order)

                    filled = await self._wait_for_fill(trade, timeout=30)

                    results.append(OrderResult(
                        success=filled,
                        order_id=trade.order.orderId,
                        status=OrderStatus.FILLED if filled else OrderStatus.CANCELLED,
                        filled_price=trade.orderStatus.avgFillPrice if filled else None,
                        message=f"Closed {qty} {pos.contract.symbol}",
                    ))
                except Exception as e:
                    results.append(OrderResult(
                        success=False,
                        status=OrderStatus.REJECTED,
                        message=f"Failed to close {pos.contract.symbol}: {e}",
                    ))

        return results
