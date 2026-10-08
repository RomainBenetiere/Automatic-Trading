"""Paper trader — simulates order execution against real market prices."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.execution.guardrails import GuardrailChecker
from app.execution.strategy import TradeAction, should_trigger_stop
from app.models.order import Order, OrderSide, OrderStatus

logger = logging.getLogger(__name__)


class PaperTrader:
    """Simulates crypto order execution without placing real orders.

    Records all decisions in the Order table with paper_mode=True.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.guardrails = GuardrailChecker(db)

    async def execute_action(
        self,
        action: TradeAction,
        current_price: float,
        portfolio_value_eur: float,
    ) -> Order | None:
        """Execute a paper trade based on a TradeAction.

        Returns the created Order record or None if rejected.
        """
        if action.rejected:
            logger.info(
                "Paper trade REJECTED: %s %s — %s",
                action.side,
                action.symbol,
                action.rejection_reason,
            )
            # Still log the rejection
            order = Order(
                symbol=action.symbol,
                side=OrderSide(action.side),
                quantity=0,
                price=current_price,
                order_value_eur=0,
                status=OrderStatus.CANCELLED,
                paper_mode=True,
                justification=f"REJECTED: {action.rejection_reason}",
                signals_snapshot=json.dumps(action.signals_snapshot),
            )
            self.db.add(order)
            await self.db.flush()
            return order

        # Compute order value and quantity
        if action.side == "buy":
            order_value = action.quote_amount_eur or 0
            quantity = order_value / current_price if current_price > 0 else 0
        else:
            quantity = action.quantity or 0
            order_value = quantity * current_price

        # Run guardrail checks for buys
        if action.side == "buy":
            checks = await self.guardrails.run_all_checks(order_value, portfolio_value_eur)
            if not self.guardrails.all_passed(checks):
                failed = [c for c in checks if not c.passed]
                rejection = "; ".join(c.message for c in failed)
                logger.warning("Paper trade BLOCKED by guardrails: %s", rejection)
                order = Order(
                    symbol=action.symbol,
                    side=OrderSide(action.side),
                    quantity=quantity,
                    price=current_price,
                    order_value_eur=order_value,
                    status=OrderStatus.CANCELLED,
                    paper_mode=True,
                    justification=f"BLOCKED: {rejection}",
                    signals_snapshot=json.dumps(action.signals_snapshot),
                )
                self.db.add(order)
                await self.db.flush()
                return order

        # Paper SELL: close open paper lots for this symbol (FIFO) at the current price
        if action.side == "sell":
            return await self._close_lots_for_sell(action, current_price)

        # Compute stop/take-profit levels for buys
        stop_loss = None
        take_profit = None
        if action.side == "buy" and current_price > 0:
            stop_loss = self.guardrails.compute_stop_loss(current_price)
            take_profit = self.guardrails.compute_take_profit(current_price)

        # Create the paper order (immediately "filled" at current price)
        order = Order(
            symbol=action.symbol,
            side=OrderSide(action.side),
            quantity=round(quantity, 8),
            price=current_price,
            order_value_eur=round(order_value, 2),
            status=OrderStatus.PAPER,
            paper_mode=True,
            justification=action.reason,
            signals_snapshot=json.dumps(action.signals_snapshot),
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
            trailing_stop_price=stop_loss,  # Initial trailing stop = stop loss
            highest_price_since_entry=current_price,
            executed_at=datetime.utcnow(),
        )

        self.db.add(order)
        await self.db.flush()

        logger.info(
            "Paper trade EXECUTED: %s %s %.8f @ %.2f (€%.2f) — SL=%.2f TP=%.2f",
            action.side.upper(),
            action.symbol,
            quantity,
            current_price,
            order_value,
            stop_loss or 0,
            take_profit or 0,
        )
        return order

    # ── Virtual paper portfolio ─────────────────────────────────────

    async def _open_lots(self, symbol: str | None = None) -> list[Order]:
        """Open paper BUY lots (oldest first), optionally for a single symbol."""
        stmt = select(Order).where(
            and_(
                Order.paper_mode == True,  # noqa: E712
                Order.side == OrderSide.BUY,
                Order.status == OrderStatus.PAPER,
                Order.closed_at.is_(None),
            )
        )
        if symbol:
            stmt = stmt.where(Order.symbol == symbol)
        result = await self.db.execute(stmt.order_by(Order.created_at, Order.id))
        return list(result.scalars().all())

    async def get_paper_state(self, get_price_fn) -> dict[str, Any]:
        """Compute the simulated paper portfolio.

        Starting capital = CRYPTO_GLOBAL_BUDGET_EUR.
        cash = start + realised P&L of closed lots − cost of open lots.
        """
        start = settings.crypto_global_budget_eur

        closed = await self.db.execute(
            select(func.coalesce(func.sum(Order.realised_pnl), 0.0)).where(
                and_(
                    Order.paper_mode == True,  # noqa: E712
                    Order.side == OrderSide.BUY,
                    Order.status == OrderStatus.PAPER,
                    Order.closed_at.is_not(None),
                )
            )
        )
        realised = float(closed.scalar() or 0.0)

        positions: dict[str, dict[str, float]] = {}
        open_cost = 0.0
        for lot in await self._open_lots():
            open_cost += lot.order_value_eur or 0.0
            pos = positions.setdefault(lot.symbol, {"quantity": 0.0, "value_eur": 0.0})
            pos["quantity"] += lot.quantity or 0.0

        for symbol, pos in positions.items():
            price = get_price_fn(symbol) or 0.0
            pos["value_eur"] = pos["quantity"] * price

        cash = start + realised - open_cost
        portfolio_value = cash + sum(p["value_eur"] for p in positions.values())
        return {
            "cash_eur": cash,
            "positions": positions,
            "portfolio_value_eur": portfolio_value,
            "realised_pnl_eur": realised,
        }

    async def _close_lots_for_sell(self, action: TradeAction, current_price: float) -> Order | None:
        """Close whole open lots FIFO until the requested quantity is covered."""
        lots = await self._open_lots(action.symbol)
        if not lots or current_price <= 0:
            logger.info("Paper SELL %s skipped — no open paper lots", action.symbol)
            return None

        target_qty = action.quantity or sum(l.quantity or 0 for l in lots)
        closed_qty = 0.0
        total_pnl = 0.0
        now = datetime.utcnow()
        for lot in lots:
            if closed_qty >= target_qty * 0.999:
                break
            pnl = (current_price - (lot.price or 0)) * (lot.quantity or 0)
            lot.realised_pnl = round(pnl, 2)
            lot.closed_at = now
            lot.justification = f"{lot.justification} | CLOSED: {action.reason}"
            closed_qty += lot.quantity or 0
            total_pnl += pnl

        # Audit record of the sell itself (P&L lives on the closed BUY lots)
        order = Order(
            symbol=action.symbol,
            side=OrderSide.SELL,
            quantity=round(closed_qty, 8),
            price=current_price,
            order_value_eur=round(closed_qty * current_price, 2),
            status=OrderStatus.PAPER,
            paper_mode=True,
            justification=f"{action.reason} (realised €{total_pnl:.2f})",
            signals_snapshot=json.dumps(action.signals_snapshot),
            executed_at=now,
        )
        self.db.add(order)
        await self.db.flush()
        logger.info(
            "Paper SELL %s: closed %.8f @ %.2f — PnL €%.2f",
            action.symbol, closed_qty, current_price, total_pnl,
        )
        return order

    async def check_open_positions(
        self,
        get_price_fn,
    ) -> list[dict[str, Any]]:
        """Check all open paper positions for stop/take-profit triggers.

        Args:
            get_price_fn: callable(symbol) -> float | None — returns current price

        Returns list of triggered close actions.
        """
        from sqlalchemy import select, and_

        stmt = select(Order).where(
            and_(
                Order.paper_mode == True,
                Order.side == OrderSide.BUY,
                Order.status == OrderStatus.PAPER,
                Order.closed_at.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        open_orders = result.scalars().all()

        triggered = []
        for order in open_orders:
            price = get_price_fn(order.symbol)
            if price is None:
                continue

            # Update trailing stop
            if order.highest_price_since_entry is not None:
                new_high = max(price, order.highest_price_since_entry)
                order.highest_price_since_entry = new_high
                order.trailing_stop_price = self.guardrails.compute_trailing_stop(
                    price, new_high
                )

            # Check stop conditions
            should_close, reason = should_trigger_stop(
                current_price=price,
                stop_loss_price=order.stop_loss_price,
                take_profit_price=order.take_profit_price,
                trailing_stop_price=order.trailing_stop_price,
            )

            if should_close:
                # Close the position
                pnl = (price - (order.price or 0)) * (order.quantity or 0)
                order.realised_pnl = round(pnl, 2)
                order.closed_at = datetime.utcnow()
                order.justification = f"{order.justification} | CLOSED: {reason}"

                triggered.append({
                    "order_id": order.id,
                    "symbol": order.symbol,
                    "reason": reason,
                    "pnl": pnl,
                    "close_price": price,
                })

                logger.info(
                    "Paper position CLOSED: %s — %s — PnL: €%.2f",
                    order.symbol,
                    reason,
                    pnl,
                )

        await self.db.flush()
        return triggered
