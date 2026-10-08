"""Safety guardrails for crypto execution — per-trade caps, stop-loss, circuit breaker."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.order import Order, OrderSide, OrderStatus
from app.models.circuit_breaker import CircuitBreakerEvent

logger = logging.getLogger(__name__)


@dataclass
class GuardrailCheck:
    """Result of a guardrail check."""

    passed: bool
    guardrail: str
    message: str
    details: dict[str, Any] | None = None


class GuardrailChecker:
    """Checks all safety guardrails before allowing trade execution."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Per-trade cap ───────────────────────────────────────────────

    def check_per_trade_cap(
        self,
        order_value_eur: float,
        portfolio_value_eur: float,
    ) -> GuardrailCheck:
        """Ensure a single trade doesn't exceed the configured portfolio percentage."""
        if portfolio_value_eur <= 0:
            return GuardrailCheck(
                passed=False,
                guardrail="per_trade_cap",
                message="Portfolio value is zero or negative",
            )

        trade_pct = (order_value_eur / portfolio_value_eur) * 100
        max_pct = settings.crypto_per_trade_cap_pct

        passed = trade_pct <= max_pct
        result = GuardrailCheck(
            passed=passed,
            guardrail="per_trade_cap",
            message=(
                f"Trade is {trade_pct:.1f}% of portfolio "
                f"({'OK' if passed else f'exceeds {max_pct}% cap'})"
            ),
            details={"trade_pct": trade_pct, "max_pct": max_pct},
        )
        logger.info("Guardrail [per_trade_cap]: %s — %s", "PASS" if passed else "FAIL", result.message)
        return result

    # ── Global budget ───────────────────────────────────────────────

    async def check_global_budget(
        self,
        new_order_value_eur: float,
    ) -> GuardrailCheck:
        """Ensure total committed doesn't exceed the global crypto budget."""
        # Sum all open/pending order values (paper lots count when in paper mode)
        statuses = [OrderStatus.PENDING, OrderStatus.FILLED]
        if not settings.crypto_live_mode:
            statuses.append(OrderStatus.PAPER)
        stmt = select(Order).where(
            and_(
                Order.status.in_(statuses),
                Order.side == OrderSide.BUY,
                Order.closed_at.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        open_orders = result.scalars().all()

        total_committed = sum(o.order_value_eur or 0 for o in open_orders)
        total_with_new = total_committed + new_order_value_eur
        max_budget = settings.crypto_global_budget_eur

        passed = total_with_new <= max_budget
        check = GuardrailCheck(
            passed=passed,
            guardrail="global_budget",
            message=(
                f"Total committed: €{total_with_new:.2f} / €{max_budget:.2f} "
                f"({'OK' if passed else 'EXCEEDS BUDGET'})"
            ),
            details={
                "total_committed": total_committed,
                "new_order_value": new_order_value_eur,
                "total_with_new": total_with_new,
                "max_budget": max_budget,
            },
        )
        logger.info("Guardrail [global_budget]: %s — %s", "PASS" if passed else "FAIL", check.message)
        return check

    # ── Circuit breaker ─────────────────────────────────────────────

    async def check_circuit_breaker(self) -> GuardrailCheck:
        """Check if a circuit breaker is currently active or should be triggered.

        Triggers on:
        1. N consecutive losing trades
        2. Cumulative loss exceeding threshold over the window period
        """
        # First, check for active (unresolved) circuit breaker events
        stmt = select(CircuitBreakerEvent).where(
            CircuitBreakerEvent.resolved_at.is_(None)
        )
        result = await self.db.execute(stmt)
        active_events = result.scalars().all()

        if active_events:
            event = active_events[0]
            return GuardrailCheck(
                passed=False,
                guardrail="circuit_breaker",
                message=(
                    f"Circuit breaker ACTIVE since {event.triggered_at} "
                    f"— reason: {event.trigger_reason}"
                ),
                details={"event_id": event.id, "reason": event.trigger_reason},
            )

        # Check for new triggers
        window_start = datetime.utcnow() - timedelta(
            days=settings.crypto_circuit_breaker_window_days
        )

        # Get recent closed orders within the window
        stmt = select(Order).where(
            and_(
                Order.closed_at >= window_start,
                Order.realised_pnl.is_not(None),
            )
        ).order_by(Order.closed_at.desc())
        result = await self.db.execute(stmt)
        recent_orders = result.scalars().all()

        if not recent_orders:
            return GuardrailCheck(
                passed=True,
                guardrail="circuit_breaker",
                message="No recent closed orders — circuit breaker not triggered",
            )

        # Check consecutive losses
        consecutive_losses = 0
        for order in recent_orders:
            if order.realised_pnl is not None and order.realised_pnl < 0:
                consecutive_losses += 1
            else:
                break

        max_consecutive = settings.crypto_circuit_breaker_consecutive_losses
        if consecutive_losses >= max_consecutive:
            # Trigger circuit breaker
            event = CircuitBreakerEvent(
                trigger_reason="consecutive_losses",
                threshold_value=float(max_consecutive),
                actual_value=float(consecutive_losses),
                details=f"Last {consecutive_losses} trades were losses",
            )
            self.db.add(event)
            await self.db.flush()

            return GuardrailCheck(
                passed=False,
                guardrail="circuit_breaker",
                message=(
                    f"Circuit breaker TRIGGERED: {consecutive_losses} "
                    f"consecutive losses (threshold: {max_consecutive})"
                ),
                details={"consecutive_losses": consecutive_losses},
            )

        # Check cumulative loss
        total_pnl = sum(o.realised_pnl or 0 for o in recent_orders)
        total_invested = sum(o.order_value_eur or 0 for o in recent_orders if o.side == OrderSide.BUY)

        if total_invested > 0:
            cumulative_loss_pct = abs(min(0, total_pnl)) / total_invested * 100
        else:
            cumulative_loss_pct = 0

        max_loss_pct = settings.crypto_circuit_breaker_cumulative_loss_pct
        if cumulative_loss_pct >= max_loss_pct:
            event = CircuitBreakerEvent(
                trigger_reason="cumulative_loss",
                threshold_value=max_loss_pct,
                actual_value=cumulative_loss_pct,
                details=f"Cumulative loss of {cumulative_loss_pct:.1f}% over {settings.crypto_circuit_breaker_window_days} days",
            )
            self.db.add(event)
            await self.db.flush()

            return GuardrailCheck(
                passed=False,
                guardrail="circuit_breaker",
                message=(
                    f"Circuit breaker TRIGGERED: {cumulative_loss_pct:.1f}% "
                    f"cumulative loss (threshold: {max_loss_pct}%)"
                ),
                details={"cumulative_loss_pct": cumulative_loss_pct},
            )

        return GuardrailCheck(
            passed=True,
            guardrail="circuit_breaker",
            message="Circuit breaker not triggered",
            details={
                "consecutive_losses": consecutive_losses,
                "cumulative_loss_pct": round(cumulative_loss_pct, 2),
            },
        )

    # ── Stop-loss / take-profit computation ─────────────────────────

    @staticmethod
    def compute_stop_loss(entry_price: float) -> float:
        """Compute the stop-loss price based on entry price."""
        return entry_price * (1 - settings.crypto_stop_loss_pct / 100)

    @staticmethod
    def compute_take_profit(entry_price: float) -> float:
        """Compute the take-profit price based on entry price."""
        return entry_price * (1 + settings.crypto_take_profit_pct / 100)

    @staticmethod
    def compute_trailing_stop(
        current_price: float,
        highest_since_entry: float,
    ) -> float:
        """Compute the trailing stop price.

        The trailing stop follows the highest price upward and never moves down.
        """
        effective_high = max(current_price, highest_since_entry)
        return effective_high * (1 - settings.crypto_trailing_stop_pct / 100)

    # ── Full pre-trade check ────────────────────────────────────────

    async def run_all_checks(
        self,
        order_value_eur: float,
        portfolio_value_eur: float,
    ) -> list[GuardrailCheck]:
        """Run all guardrail checks. Returns list of results (all must pass)."""
        checks = [
            self.check_per_trade_cap(order_value_eur, portfolio_value_eur),
            await self.check_global_budget(order_value_eur),
            await self.check_circuit_breaker(),
        ]
        return checks

    @staticmethod
    def all_passed(checks: list[GuardrailCheck]) -> bool:
        """Return True if all guardrail checks passed."""
        return all(c.passed for c in checks)
