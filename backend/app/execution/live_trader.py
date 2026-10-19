"""Live trader — real order execution via Bitvavo API.

Extends the same logic as PaperTrader but actually calls the Bitvavo API.
Only activatable after paper trading period and explicit config change.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.bitvavo import BitvavoClient
from app.config import settings
from app.execution.guardrails import GuardrailChecker
from app.execution.strategy import TradeAction, should_trigger_stop
from app.models.order import Order, OrderSide, OrderStatus

logger = logging.getLogger(__name__)


class LiveTrader:
    """Executes real crypto orders via the Bitvavo API.

    Mirrors PaperTrader logic with real order submission.
    """

    def __init__(self, db: AsyncSession, bitvavo: BitvavoClient) -> None:
        self.db = db
        self.bitvavo = bitvavo
        self.guardrails = GuardrailChecker(db)

    def _is_enabled(self) -> bool:
        """Check if live trading is enabled."""
        return settings.crypto_live_mode

    async def execute_action(
        self,
        action: TradeAction,
        current_price: float,
        portfolio_value_eur: float,
        current_position_value_eur: float = 0.0,
    ) -> Order | None:
        """Execute a live trade via Bitvavo.

        Returns the created Order record or None if rejected/disabled.
        """
        if not self._is_enabled():
            logger.warning("Live trading is DISABLED — skipping action for %s", action.symbol)
            return None

        if action.rejected:
            logger.info(
                "Live trade REJECTED: %s %s — %s",
                action.side,
                action.symbol,
                action.rejection_reason,
            )
            order = Order(
                symbol=action.symbol,
                side=OrderSide(action.side),
                quantity=0,
                price=current_price,
                order_value_eur=0,
                status=OrderStatus.CANCELLED,
                paper_mode=False,
                justification=f"REJECTED: {action.rejection_reason}",
                signals_snapshot=json.dumps(action.signals_snapshot),
            )
            self.db.add(order)
            await self.db.flush()
            return order

        # Compute order parameters
        if action.side == "buy":
            order_value = action.quote_amount_eur or 0
            quantity = order_value / current_price if current_price > 0 else 0
        else:
            quantity = action.quantity or 0
            order_value = quantity * current_price

        # Run guardrail checks for buys
        if action.side == "buy":
            checks = await self.guardrails.run_all_checks(action.symbol, order_value, portfolio_value_eur, current_position_value_eur)
            if not self.guardrails.all_passed(checks):
                failed = [c for c in checks if not c.passed]
                rejection = "; ".join(c.message for c in failed)
                logger.warning("Live trade BLOCKED by guardrails: %s", rejection)
                order = Order(
                    symbol=action.symbol,
                    side=OrderSide(action.side),
                    quantity=quantity,
                    price=current_price,
                    order_value_eur=order_value,
                    status=OrderStatus.CANCELLED,
                    paper_mode=False,
                    justification=f"BLOCKED: {rejection}",
                    signals_snapshot=json.dumps(action.signals_snapshot),
                )
                self.db.add(order)
                await self.db.flush()
                return order

        # Compute stop/take-profit
        stop_loss = None
        take_profit = None
        if action.side == "buy" and current_price > 0:
            stop_loss = self.guardrails.compute_stop_loss(current_price)
            take_profit = self.guardrails.compute_take_profit(current_price)

        # Create order record (pending)
        order = Order(
            symbol=action.symbol,
            side=OrderSide(action.side),
            quantity=round(quantity, 8),
            price=current_price,
            order_value_eur=round(order_value, 2),
            status=OrderStatus.PENDING,
            paper_mode=False,
            justification=action.reason,
            signals_snapshot=json.dumps(action.signals_snapshot),
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
            trailing_stop_price=stop_loss,
            highest_price_since_entry=current_price,
        )
        self.db.add(order)
        await self.db.flush()

        # ── Execute via Bitvavo ────────────────────────────────────
        try:
            if action.side == "buy":
                result = self.bitvavo.place_market_order(
                    market=action.symbol,
                    side="buy",
                    quote_amount=order_value,
                )
            else:
                result = self.bitvavo.place_market_order(
                    market=action.symbol,
                    side="sell",
                    amount=quantity,
                )

            if isinstance(result, dict) and "error" not in result:
                order.exchange_order_id = result.get("orderId")
                order.status = OrderStatus.FILLED
                order.executed_at = datetime.utcnow()

                # Update with actual fill price if available
                fill_price = result.get("price") or result.get("fills", [{}])[0].get("price")
                if fill_price:
                    order.price = float(fill_price)
                filled_amount = result.get("filledAmount")
                if filled_amount and float(filled_amount) > 0:
                    order.quantity = float(filled_amount)

                # Recalculate stop-loss and take-profit from actual fill price
                if action.side == "buy" and order.price:
                    order.stop_loss_price = self.guardrails.compute_stop_loss(order.price)
                    order.take_profit_price = self.guardrails.compute_take_profit(order.price)
                    order.trailing_stop_price = order.stop_loss_price
                    order.highest_price_since_entry = order.price

                logger.info(
                    "Live trade EXECUTED: %s %s %.8f @ %.2f — order_id=%s",
                    action.side.upper(),
                    action.symbol,
                    order.quantity,
                    order.price or current_price,
                    order.exchange_order_id,
                )

                # Send native stopLoss order directly to Bitvavo
                if action.side == "buy" and order.stop_loss_price and order.quantity > 0:
                    try:
                        sl_res = self.bitvavo.place_stop_loss_order(
                            market=order.symbol,
                            side="sell",
                            amount=order.quantity,
                            trigger_price=order.stop_loss_price,
                        )
                        if isinstance(sl_res, dict) and "orderId" in sl_res:
                            order.stop_loss_order_id = sl_res.get("orderId")
                            logger.info(
                                "Native Bitvavo Stop-Loss placed for %s: orderId=%s trigger=%.2f",
                                order.symbol,
                                order.stop_loss_order_id,
                                order.stop_loss_price,
                            )
                        else:
                            logger.error(
                                "Failed to place native Bitvavo Stop-Loss for %s: %s",
                                order.symbol,
                                sl_res,
                            )
                    except Exception as sl_err:
                        logger.exception("Exception placing native stop-loss on Bitvavo for %s: %s", order.symbol, sl_err)
            else:
                order.status = OrderStatus.FAILED
                error_msg = result.get("error", "Unknown error") if isinstance(result, dict) else str(result)
                order.justification = f"{order.justification} | ERROR: {error_msg}"
                logger.error("Live trade FAILED: %s — %s", action.symbol, error_msg)

        except Exception as e:
            order.status = OrderStatus.FAILED
            order.justification = f"{order.justification} | EXCEPTION: {e}"
            logger.exception("Live trade exception for %s", action.symbol)

        await self.db.flush()
        return order

    async def check_open_positions(
        self,
    ) -> list[dict[str, Any]]:
        """Check all open live positions for stop triggers and update trailing stops.

        1. Checks if native Bitvavo stop-loss order was filled.
        2. Queries current ticker price.
        3. Updates highest price since entry and trailing stop level.
        4. If trailing stop moved up, cancels and replaces the native stop-loss on Bitvavo.
        5. If take-profit or stop condition met, cancels stop order and closes position via market sell.
        """
        from sqlalchemy import and_, select

        stmt = select(Order).where(
            and_(
                Order.paper_mode == False,
                Order.side == OrderSide.BUY,
                Order.status == OrderStatus.FILLED,
                Order.closed_at.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        open_orders = result.scalars().all()

        triggered = []
        for order in open_orders:
            # 1. Check if the native stop-loss on Bitvavo has already filled
            if order.stop_loss_order_id:
                try:
                    status_res = self.bitvavo.get_order_status(order.symbol, order.stop_loss_order_id)
                    order_status = status_res.get("status") if isinstance(status_res, dict) else None
                    if order_status == "filled":
                        fill_price = float(status_res.get("price") or order.stop_loss_price or order.price or 0.0)
                        pnl = (fill_price - (order.price or 0.0)) * (order.quantity or 0.0)
                        order.realised_pnl = round(pnl, 2)
                        order.closed_at = datetime.utcnow()
                        order.justification = (
                            f"{order.justification} | CLOSED: Native Bitvavo stop-loss filled @ {fill_price:.2f}"
                        )
                        triggered.append({
                            "order_id": order.id,
                            "symbol": order.symbol,
                            "reason": "bitvavo_native_stop_loss_filled",
                            "pnl": pnl,
                            "close_price": fill_price,
                        })
                        logger.info(
                            "Live position CLOSED via native Bitvavo stop: %s @ %.2f — PnL: €%.2f",
                            order.symbol,
                            fill_price,
                            pnl,
                        )
                        continue
                except Exception as e:
                    logger.warning("Error checking stop-loss status for %s (%s): %s", order.symbol, order.stop_loss_order_id, e)

            # 2. Get current ticker price
            price = self.bitvavo.get_ticker_price(order.symbol)
            if price is None:
                continue

            # 3. Update trailing stop (ratchet upward only once position has risen above entry price)
            entry_price = order.price or price
            highest = order.highest_price_since_entry or entry_price
            new_high = max(price, highest)
            order.highest_price_since_entry = new_high

            if new_high > entry_price:
                new_trailing = self.guardrails.compute_trailing_stop(price, new_high)

                # Check if trailing stop moved UP
                prev_trailing = order.trailing_stop_price or order.stop_loss_price or 0.0
                if new_trailing > prev_trailing:
                    order.trailing_stop_price = new_trailing
                    logger.info(
                        "Trailing stop raised for %s: %.2f -> %.2f (high: %.2f)",
                        order.symbol,
                        prev_trailing,
                        new_trailing,
                        new_high,
                    )
                    # Cancel previous Bitvavo stop-loss and place a new one with the higher trailing price
                    if order.stop_loss_order_id:
                        try:
                            self.bitvavo.cancel_order(order.symbol, order.stop_loss_order_id)
                            order.stop_loss_order_id = None
                        except Exception as ce:
                            logger.warning("Error cancelling old stop order on Bitvavo: %s", ce)

                    try:
                        new_stop_res = self.bitvavo.place_stop_loss_order(
                            market=order.symbol,
                            side="sell",
                            amount=order.quantity,
                            trigger_price=new_trailing,
                        )
                        if isinstance(new_stop_res, dict) and "orderId" in new_stop_res:
                            order.stop_loss_order_id = new_stop_res.get("orderId")
                            logger.info(
                                "Updated native Bitvavo Stop-Loss for %s: orderId=%s trigger=%.2f",
                                order.symbol,
                                order.stop_loss_order_id,
                                new_trailing,
                            )
                    except Exception as ne:
                        logger.exception("Error placing updated stop-loss on Bitvavo: %s", ne)

            # 4. Check if take-profit or stop condition met
            should_close, reason = should_trigger_stop(
                current_price=price,
                stop_loss_price=order.stop_loss_price,
                take_profit_price=order.take_profit_price,
                trailing_stop_price=order.trailing_stop_price,
            )

            if should_close:
                # Cancel stop order if still pending
                if order.stop_loss_order_id:
                    try:
                        self.bitvavo.cancel_order(order.symbol, order.stop_loss_order_id)
                        order.stop_loss_order_id = None
                    except Exception as ce:
                        logger.warning("Error cancelling stop-loss before market sell for %s: %s", order.symbol, ce)

                # Place a real sell order
                try:
                    sell_result = self.bitvavo.place_market_order(
                        market=order.symbol,
                        side="sell",
                        amount=order.quantity,
                    )

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
                        "sell_result": sell_result,
                    })

                    logger.info(
                        "Live position CLOSED: %s — %s — PnL: €%.2f",
                        order.symbol,
                        reason,
                        pnl,
                    )
                except Exception as e:
                    logger.exception("Failed to close position %s: %s", order.symbol, e)

        await self.db.flush()
        return triggered
