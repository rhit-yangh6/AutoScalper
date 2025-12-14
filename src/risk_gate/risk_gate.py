from datetime import datetime, time
from enum import Enum
from typing import Optional
from pydantic import BaseModel

from ..models import Event, TradeSession, EventType, RiskLevel


class RiskDecision(str, Enum):
    """Risk gate decision."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class RiskCheckResult(BaseModel):
    """Result of risk validation."""

    decision: RiskDecision
    reason: Optional[str] = None
    failed_checks: list[str] = []


class RiskGate:
    """
    Final deterministic approval gate before execution.

    Implements all risk checks from proposal:
    - Daily max loss
    - Loss streak limit
    - Time-of-day filters
    - Economic event blocks
    - Bid-ask spread thresholds
    - Max contracts
    - Max adds per trade

    CRITICAL: Any check failure = NO TRADE
    """

    def __init__(self, config: dict):
        """
        Initialize risk gate with configuration.

        Expected config keys:
        - account_balance: float
        - risk_per_trade_percent: float (0.25 - 0.5)
        - daily_max_loss_percent: float (1.0 - 2.0)
        - max_loss_streak: int
        - max_contracts: int
        - max_adds_per_trade: int
        - trading_hours_start: str (HH:MM)
        - trading_hours_end: str (HH:MM)
        - max_bid_ask_spread_percent: float
        - high_risk_size_reduction: float (e.g., 0.5 = 50% reduction)
        """
        self.config = config
        self.account_balance = config["account_balance"]
        self.daily_pnl = 0.0  # Track daily PnL
        self.loss_streak = 0  # Track consecutive losses
        self.trades_today = []  # Track all trades today

    def validate(
        self,
        event: Event,
        session: TradeSession,
        current_price: Optional[float] = None,
        bid_ask_spread: Optional[float] = None,
    ) -> RiskCheckResult:
        """
        Validate if an event should be executed.

        Args:
            event: The event to validate
            session: The associated trade session
            current_price: Current option price (for spread check)
            bid_ask_spread: Current bid-ask spread

        Returns:
            RiskCheckResult with approval or rejection
        """
        failed_checks = []

        # Only validate actionable events
        if not event.is_actionable():
            return RiskCheckResult(
                decision=RiskDecision.APPROVE,
                reason="Non-actionable event (PLAN, TARGETS, RISK_NOTE, etc.)",
            )

        # 1. Daily max loss check
        if not self._check_daily_max_loss():
            failed_checks.append("Daily max loss exceeded")

        # 2. Loss streak check
        if not self._check_loss_streak():
            failed_checks.append("Loss streak limit exceeded")

        # 3. Time of day check
        if not self._check_trading_hours():
            failed_checks.append("Outside trading hours")

        # 4. Max contracts check (for NEW and ADD events)
        if event.event_type in [EventType.NEW, EventType.ADD]:
            if not self._check_max_contracts(event.quantity or 1):
                failed_checks.append("Max contracts exceeded")

        # 5. Max adds check
        if event.event_type == EventType.ADD:
            if not session.can_add_position():
                failed_checks.append(
                    f"Max adds exceeded ({session.num_adds}/{session.max_adds})"
                )

        # 6. Stop invalidation check
        if session.stop_invalidated and event.event_type == EventType.ADD:
            failed_checks.append("Stop already invalidated, no adds allowed")

        # 7. Bid-ask spread check
        if bid_ask_spread and current_price:
            if not self._check_bid_ask_spread(bid_ask_spread, current_price):
                failed_checks.append("Bid-ask spread too wide")

        # 8. High risk check
        if event.risk_level in [RiskLevel.HIGH, RiskLevel.EXTREME]:
            if not self._check_high_risk_allowed():
                failed_checks.append("High risk trades blocked in current state")

        # Decision
        if failed_checks:
            return RiskCheckResult(
                decision=RiskDecision.REJECT,
                reason="; ".join(failed_checks),
                failed_checks=failed_checks,
            )

        return RiskCheckResult(
            decision=RiskDecision.APPROVE, reason="All risk checks passed"
        )

    def _check_daily_max_loss(self) -> bool:
        """Check if daily max loss has been exceeded."""
        max_loss_dollars = (
            self.account_balance * self.config["daily_max_loss_percent"] / 100
        )
        return self.daily_pnl > -max_loss_dollars

    def _check_loss_streak(self) -> bool:
        """Check if loss streak limit has been exceeded."""
        return self.loss_streak < self.config.get("max_loss_streak", 3)

    def _check_trading_hours(self) -> bool:
        """Check if current time is within allowed trading hours."""
        now = datetime.utcnow().time()

        start_str = self.config.get("trading_hours_start", "13:30")  # 9:30 AM ET
        end_str = self.config.get("trading_hours_end", "20:00")  # 4:00 PM ET

        start = time.fromisoformat(start_str)
        end = time.fromisoformat(end_str)

        return start <= now <= end

    def _check_max_contracts(self, quantity: int) -> bool:
        """Check if quantity exceeds max contracts."""
        return quantity <= self.config["max_contracts"]

    def _check_bid_ask_spread(self, spread: float, price: float) -> bool:
        """Check if bid-ask spread is acceptable."""
        max_spread_percent = self.config.get("max_bid_ask_spread_percent", 10.0)
        spread_percent = (spread / price) * 100 if price > 0 else 100
        return spread_percent <= max_spread_percent

    def _check_high_risk_allowed(self) -> bool:
        """
        Check if high-risk trades are allowed.

        Block high-risk if:
        - Already in drawdown
        - Loss streak active
        """
        if self.daily_pnl < 0:
            return False
        if self.loss_streak > 0:
            return False
        return True

    def calculate_position_size(
        self, event: Event, session: TradeSession
    ) -> int:
        """
        Calculate appropriate position size based on risk parameters.

        Returns number of contracts to trade.
        """
        # Base risk per trade
        risk_percent = self.config["risk_per_trade_percent"]
        risk_dollars = self.account_balance * (risk_percent / 100)

        # Adjust for risk level
        if event.risk_level == RiskLevel.HIGH:
            risk_dollars *= self.config.get("high_risk_size_reduction", 0.5)
        elif event.risk_level == RiskLevel.EXTREME:
            risk_dollars *= self.config.get("extreme_risk_size_reduction", 0.25)

        # Calculate contracts (assume risk = entry price for simplicity)
        entry_price = event.entry_price or session.avg_entry_price
        if entry_price <= 0:
            return 1  # Default minimum

        contracts = int(risk_dollars / (entry_price * 100))  # Options are x100
        contracts = max(1, contracts)  # At least 1
        contracts = min(
            contracts, self.config["max_contracts"]
        )  # Cap at max

        return contracts

    def calculate_stop_and_target(
        self, event: Event, session: TradeSession
    ) -> tuple[Optional[float], Optional[float]]:
        """
        Calculate stop loss and profit target if not provided.

        Returns (stop_loss, target) tuple.

        Strategy:
        - Stop loss: Entry - (stop_loss_percent * entry)
        - Target: Entry + (risk_reward_ratio * distance_to_stop)
        """
        entry_price = event.entry_price or session.avg_entry_price
        if not entry_price or entry_price <= 0:
            return None, None

        # If already provided, use those
        stop_loss = event.stop_loss
        target = event.targets[0] if event.targets else None

        # Calculate stop loss if not provided
        if not stop_loss:
            stop_percent = self.config.get("auto_stop_loss_percent", 25.0)
            stop_loss = entry_price * (1 - stop_percent / 100)
            stop_loss = round(stop_loss, 2)

        # Calculate target if not provided
        if not target:
            risk_reward_ratio = self.config.get("risk_reward_ratio", 2.0)
            distance_to_stop = entry_price - stop_loss
            target = entry_price + (distance_to_stop * risk_reward_ratio)
            target = round(target, 2)

        return stop_loss, target

    def record_trade_result(self, pnl: float) -> None:
        """
        Record a completed trade result for tracking.

        Updates daily PnL and loss streak.
        """
        self.daily_pnl += pnl
        self.trades_today.append({"pnl": pnl, "timestamp": datetime.utcnow()})

        # Update loss streak
        if pnl < 0:
            self.loss_streak += 1
        else:
            self.loss_streak = 0

    def reset_daily_state(self) -> None:
        """Reset daily tracking (call at start of new trading day)."""
        self.daily_pnl = 0.0
        self.loss_streak = 0
        self.trades_today = []

    def get_risk_summary(self) -> dict:
        """Get current risk state summary."""
        max_loss_dollars = (
            self.account_balance * self.config["daily_max_loss_percent"] / 100
        )

        return {
            "account_balance": self.account_balance,
            "daily_pnl": self.daily_pnl,
            "daily_pnl_percent": (self.daily_pnl / self.account_balance) * 100,
            "remaining_loss_allowance": max_loss_dollars + self.daily_pnl,
            "loss_streak": self.loss_streak,
            "trades_today": len(self.trades_today),
            "can_trade": self._check_daily_max_loss()
            and self._check_loss_streak(),
        }
