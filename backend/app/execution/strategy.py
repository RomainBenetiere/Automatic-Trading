"""Strategy / decision engine — converts scores + guardrails into trade actions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.analysis.composite import CompositeResult
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class TradeAction:
    """A concrete trade action to execute (or reject)."""

    symbol: str
    side: str  # "buy" or "sell"
    quantity: float | None = None
    quote_amount_eur: float | None = None  # For buys: how much EUR to spend
    reason: str = ""
    signals_snapshot: dict = field(default_factory=dict)
    rejected: bool = False
    rejection_reason: str = ""


def decide_crypto_action(
    symbol: str,
    composite_result: CompositeResult,
    current_position_value_eur: float,
    available_budget_eur: float,
    portfolio_value_eur: float,
    current_price: float | None = None,
) -> TradeAction | None:
    """Decide whether to buy, sell, or hold a crypto asset.

    Args:
        symbol: market pair (e.g. "BTC-EUR")
        composite_result: the composite score and signal
        current_position_value_eur: current EUR value of existing position
        available_budget_eur: how much EUR is available to deploy
        portfolio_value_eur: total crypto portfolio value
        current_price: latest price (for quantity computation)

    Returns a TradeAction or None (hold / no action).
    """
    signal = composite_result.signal
    score = composite_result.composite_score

    signals_snapshot = {
        "composite_score": score,
        "signal": signal,
        "technical": composite_result.technical_score,
        "fundamental": composite_result.fundamental_score,
        "dividend": composite_result.dividend_score,
        "weights": composite_result.weights,
    }

    # ── BUY logic ──────────────────────────────────────────────────
    if signal in ("strong_buy", "buy"):
        if available_budget_eur <= 0:
            return TradeAction(
                symbol=symbol,
                side="buy",
                rejected=True,
                rejection_reason="No available budget",
                signals_snapshot=signals_snapshot,
            )

        # Position sizing: proportional to signal confidence
        if signal == "strong_buy":
            size_pct = min(settings.crypto_per_trade_cap_pct, 5.0)
        else:
            size_pct = min(settings.crypto_per_trade_cap_pct, 3.0)

        order_value = min(
            portfolio_value_eur * (size_pct / 100),
            available_budget_eur,
        )

        # Bitvavo minimum order is €5. Bump small orders up to the minimum
        # when the per-trade cap and available budget still allow it.
        min_order = 5.0
        if order_value < min_order:
            max_allowed = min(
                portfolio_value_eur * settings.crypto_per_trade_cap_pct / 100,
                available_budget_eur,
            )
            if max_allowed >= min_order:
                order_value = min_order
            else:
                logger.info(
                    "Strategy: %s buy skipped — €%.2f below €%.0f minimum "
                    "(max allowed €%.2f)", symbol, order_value, min_order, max_allowed,
                )
                return None

        return TradeAction(
            symbol=symbol,
            side="buy",
            quote_amount_eur=round(order_value, 2),
            reason=(
                f"Signal: {signal} (score: {score:.1f}). "
                f"Allocating €{order_value:.2f} ({size_pct:.1f}% of portfolio)."
            ),
            signals_snapshot=signals_snapshot,
        )

    # ── SELL logic ─────────────────────────────────────────────────
    elif signal in ("sell", "reduce"):
        if current_position_value_eur <= 0:
            return None  # Nothing to sell

        if signal == "sell":
            sell_pct = 1.0  # Sell all
        else:
            sell_pct = 0.5  # Reduce by half

        if current_price and current_price > 0:
            quantity = (current_position_value_eur * sell_pct) / current_price
        else:
            quantity = None

        return TradeAction(
            symbol=symbol,
            side="sell",
            quantity=round(quantity, 8) if quantity else None,
            reason=(
                f"Signal: {signal} (score: {score:.1f}). "
                f"{'Closing' if sell_pct == 1.0 else 'Reducing'} position."
            ),
            signals_snapshot=signals_snapshot,
        )

    # ── HOLD ───────────────────────────────────────────────────────
    logger.info(
        "Strategy: %s → HOLD (score=%.1f, signal=%s)", symbol, score, signal
    )
    return None


def should_trigger_stop(
    current_price: float,
    stop_loss_price: float | None,
    take_profit_price: float | None,
    trailing_stop_price: float | None,
) -> tuple[bool, str]:
    """Check if any stop condition is met.

    Returns (triggered, reason).
    """
    if stop_loss_price and current_price <= stop_loss_price:
        return True, f"Stop-loss triggered at {current_price} (stop: {stop_loss_price})"

    if take_profit_price and current_price >= take_profit_price:
        return True, f"Take-profit triggered at {current_price} (target: {take_profit_price})"

    if trailing_stop_price and current_price <= trailing_stop_price:
        return True, f"Trailing stop triggered at {current_price} (trail: {trailing_stop_price})"

    return False, ""
