"""
Risk Gate for MNQ Futures Trading

Final deterministic approval gate before execution.
Implements all risk checks for futures trading.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel

from ..models import Event, TradeSession, EventType, RiskLevel


# MNQ contract specifications
MNQ_POINT_VALUE = 2.0  # $2 per point for MNQ
MNQ_DEFAULT_MARGIN = 2000.0  # Default margin per contract for MNQ


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

    Implements risk checks for MNQ futures:
    - Daily max loss
    - Loss streak limit

    CRITICAL: Any check failure = NO TRADE
    """

    def __init__(self, config: dict):
        """
        Initialize risk gate with configuration.

        Expected config keys:
        - account_balance: float (fallback if IBKR balance unavailable)
        - daily_max_loss: float (dollar amount, e.g., 500)
        - max_loss_streak: int
        - num_contracts: int (0 = auto-calculate from balance)
        - margin_per_contract: float (margin required per contract)
        """
        self.config = config
        self.account_balance = config.get("account_balance", 10000.0)
        self.futures_price = 0.0  # Updated with live price
        self.daily_pnl = 0.0
        self.loss_streak = 0
        self.trades_today = []

    def update_account_balance(self, balance: float) -> None:
        """Update account balance dynamically from IBKR."""
        if balance > 0:
            self.account_balance = balance

    def update_futures_price(self, price: float) -> None:
        """Update current futures price for margin calculations."""
        if price > 0:
            self.futures_price = price

    def update_margin_requirement(self, margin: float) -> None:
        """Update margin requirement per contract from IBKR."""
        if margin > 0:
            self.config["margin_per_contract"] = margin
            print(f"Margin requirement updated: ${margin:,.2f} per contract")

    def validate(
        self,
        event: Event,
        session: TradeSession,
        unrealized_pnl: float = 0.0,
    ) -> RiskCheckResult:
        """
        Validate if an event should be executed.

        Args:
            event: The event to validate
            session: The associated trade session
            unrealized_pnl: Current unrealized P&L from open positions
        """
        failed_checks = []

        # Only validate actionable events
        if not event.is_actionable():
            return RiskCheckResult(
                decision=RiskDecision.APPROVE,
                reason="Non-actionable event",
            )

        # 1. Daily max loss check (including unrealized P&L)
        if not self._check_daily_max_loss(unrealized_pnl):
            failed_checks.append(
                f"Daily max loss exceeded (Realized: ${self.daily_pnl:.2f}, Unrealized: ${unrealized_pnl:.2f})"
            )

        # 2. Loss streak check
        if not self._check_loss_streak():
            failed_checks.append("Loss streak limit exceeded")

        # 3. High risk check
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
            decision=RiskDecision.APPROVE,
            reason="All risk checks passed"
        )

    def _check_daily_max_loss(self, unrealized_pnl: float = 0.0) -> bool:
        """
        Check if daily max loss has been exceeded.

        Uses dollar-based max loss for futures (not percentage).
        """
        max_loss = self.config.get("daily_max_loss", 500.0)
        total_pnl = self.daily_pnl + unrealized_pnl
        return total_pnl > -max_loss

    def _check_loss_streak(self) -> bool:
        """Check if loss streak limit has been exceeded."""
        return self.loss_streak < self.config.get("max_loss_streak", 3)

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
        Calculate position size for the trade.

        If num_contracts > 0: use fixed contract count
        If num_contracts = 0: auto-calculate based on account balance and margin
        """
        num_contracts = self.config.get("num_contracts", 1)

        # Fixed contract count
        if num_contracts > 0:
            return num_contracts

        # Auto-calculate: buy as many contracts as balance allows (with safety buffer)
        margin_per_contract = self.config.get("margin_per_contract", MNQ_DEFAULT_MARGIN)
        margin_buffer = self.config.get("margin_buffer", 0.80)  # Use 80% of balance, keep 20% buffer

        if margin_per_contract <= 0:
            print("⚠️ Invalid margin_per_contract, defaulting to 1 contract")
            return 1

        # Apply safety buffer - only use portion of balance for margin
        usable_balance = self.account_balance * margin_buffer

        # Calculate max contracts based on usable balance
        max_affordable = int(usable_balance / margin_per_contract)

        if max_affordable <= 0:
            print(f"⚠️ Insufficient balance for margin")
            print(f"   Balance: ${self.account_balance:.2f} × {margin_buffer:.0%} = ${usable_balance:.2f} usable")
            print(f"   Margin required: ${margin_per_contract:.2f} per contract")
            return 0

        buffer_amount = self.account_balance - (max_affordable * margin_per_contract)
        print(f"  Auto-sized: {max_affordable} contracts")
        print(f"    Balance: ${self.account_balance:.2f} × {margin_buffer:.0%} = ${usable_balance:.2f} usable")
        print(f"    Margin: ${margin_per_contract:.2f} × {max_affordable} = ${max_affordable * margin_per_contract:.2f}")
        print(f"    Buffer: ${buffer_amount:.2f}")
        return max_affordable

    def record_trade_result(self, pnl: float) -> None:
        """
        Record a completed trade result for tracking.

        Updates daily PnL and loss streak.
        """
        self.daily_pnl += pnl
        self.trades_today.append({"pnl": pnl, "timestamp": datetime.now(timezone.utc)})

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
        max_loss = self.config.get("daily_max_loss", 500.0)

        return {
            "account_balance": self.account_balance,
            "daily_pnl": self.daily_pnl,
            "daily_pnl_percent": (self.daily_pnl / self.account_balance) * 100 if self.account_balance > 0 else 0,
            "remaining_loss_allowance": max_loss + self.daily_pnl,
            "loss_streak": self.loss_streak,
            "trades_today": len(self.trades_today),
            "can_trade": self._check_daily_max_loss() and self._check_loss_streak(),
        }
