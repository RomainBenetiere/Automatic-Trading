"""Crypto execution API routes — positions, orders, guardrails, performance."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, desc, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.bitvavo import BitvavoClient
from app.config import settings
from app.database import get_db
from app.models.circuit_breaker import CircuitBreakerEvent
from app.models.order import Order, OrderSide, OrderStatus

router = APIRouter(prefix="/api/crypto", tags=["crypto"])


@router.get("/positions")
async def get_crypto_positions() -> list[dict[str, Any]]:
    """Get current Bitvavo crypto balances."""
    client = BitvavoClient()
    balances = client.get_balances()

    positions = []
    for bal in balances:
        symbol = bal["symbol"]
        if symbol == "EUR":
            positions.append({**bal, "market_value_eur": bal["total"]})
            continue

        market = f"{symbol}-EUR"
        price = client.get_ticker_price(market)
        ticker = client.get_ticker_24h(market)

        # Bitvavo's ticker24h exposes open/last but no percentage field
        change_24h = None
        try:
            open_px = float(ticker.get("open") or 0)
            last_px = float(ticker.get("last") or price or 0)
            if open_px > 0 and last_px > 0:
                change_24h = round((last_px - open_px) / open_px * 100, 2)
        except (TypeError, ValueError):
            pass

        positions.append({
            **bal,
            "market": market,
            "current_price": price,
            "market_value_eur": bal["total"] * price if price else None,
            "change_24h_pct": change_24h,
        })

    return positions


@router.get("/orders")
async def get_orders(
    paper_only: bool | None = None,
    symbol: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get crypto order history."""
    stmt = select(Order).order_by(desc(Order.created_at))

    if paper_only is not None:
        stmt = stmt.where(Order.paper_mode == paper_only)
    if symbol:
        stmt = stmt.where(Order.symbol == symbol)

    stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    orders = result.scalars().all()

    return [
        {
            "id": o.id,
            "symbol": o.symbol,
            "side": o.side.value,
            "quantity": o.quantity,
            "price": o.price,
            "order_value_eur": o.order_value_eur,
            "status": o.status.value,
            "paper_mode": o.paper_mode,
            "justification": o.justification,
            "signals_snapshot": o.signals_snapshot,
            "stop_loss_price": o.stop_loss_price,
            "take_profit_price": o.take_profit_price,
            "trailing_stop_price": o.trailing_stop_price,
            "realised_pnl": o.realised_pnl,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "executed_at": o.executed_at.isoformat() if o.executed_at else None,
            "closed_at": o.closed_at.isoformat() if o.closed_at else None,
        }
        for o in orders
    ]


@router.get("/orders/{order_id}")
async def get_order_detail(
    order_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get detailed info for a single order."""
    stmt = select(Order).where(Order.id == order_id)
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail=f"Order not found: {order_id}")

    return {
        "id": order.id,
        "symbol": order.symbol,
        "side": order.side.value,
        "quantity": order.quantity,
        "price": order.price,
        "order_value_eur": order.order_value_eur,
        "status": order.status.value,
        "paper_mode": order.paper_mode,
        "justification": order.justification,
        "signals_snapshot": order.signals_snapshot,
        "stop_loss_price": order.stop_loss_price,
        "take_profit_price": order.take_profit_price,
        "trailing_stop_price": order.trailing_stop_price,
        "highest_price_since_entry": order.highest_price_since_entry,
        "exchange_order_id": order.exchange_order_id,
        "realised_pnl": order.realised_pnl,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "executed_at": order.executed_at.isoformat() if order.executed_at else None,
        "closed_at": order.closed_at.isoformat() if order.closed_at else None,
    }


@router.get("/guardrails/status")
async def get_guardrail_status(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get current status of all guardrails."""
    # Check circuit breaker
    stmt = select(CircuitBreakerEvent).where(
        CircuitBreakerEvent.resolved_at.is_(None)
    )
    result = await db.execute(stmt)
    active_breakers = result.scalars().all()

    # Calculate recent stats
    window_start = datetime.utcnow() - timedelta(
        days=settings.crypto_circuit_breaker_window_days
    )
    stmt = select(Order).where(
        and_(
            Order.closed_at >= window_start,
            Order.realised_pnl.is_not(None),
        )
    ).order_by(desc(Order.closed_at))
    result = await db.execute(stmt)
    recent_orders = result.scalars().all()

    consecutive_losses = 0
    for o in recent_orders:
        if o.realised_pnl is not None and o.realised_pnl < 0:
            consecutive_losses += 1
        else:
            break

    total_pnl = sum(o.realised_pnl or 0 for o in recent_orders)
    total_invested = sum(
        o.order_value_eur or 0 for o in recent_orders if o.side == OrderSide.BUY
    )
    cumulative_loss_pct = (
        abs(min(0, total_pnl)) / total_invested * 100 if total_invested > 0 else 0
    )

    return {
        "circuit_breaker": {
            "active": len(active_breakers) > 0,
            "events": [
                {
                    "id": e.id,
                    "reason": e.trigger_reason,
                    "triggered_at": e.triggered_at.isoformat(),
                }
                for e in active_breakers
            ],
        },
        "per_trade_cap": {
            "max_pct": settings.crypto_per_trade_cap_pct,
            "status": "ok",
        },
        "stop_loss": {
            "pct": settings.crypto_stop_loss_pct,
            "status": "ok",
        },
        "trailing_stop": {
            "pct": settings.crypto_trailing_stop_pct,
            "status": "ok",
        },
        "take_profit": {
            "pct": settings.crypto_take_profit_pct,
            "status": "ok",
        },
        "global_budget": {
            "max_eur": settings.crypto_global_budget_eur,
            "status": "ok",
        },
        "recent_stats": {
            "consecutive_losses": consecutive_losses,
            "max_consecutive_losses": settings.crypto_circuit_breaker_consecutive_losses,
            "cumulative_loss_pct": round(cumulative_loss_pct, 2),
            "max_cumulative_loss_pct": settings.crypto_circuit_breaker_cumulative_loss_pct,
            "window_days": settings.crypto_circuit_breaker_window_days,
        },
        "mode": "live" if settings.crypto_live_mode else "paper",
    }


@router.get("/circuit-breaker/events")
async def get_circuit_breaker_events(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get circuit breaker event history."""
    stmt = (
        select(CircuitBreakerEvent)
        .order_by(desc(CircuitBreakerEvent.triggered_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    events = result.scalars().all()

    return [
        {
            "id": e.id,
            "trigger_reason": e.trigger_reason,
            "threshold_value": e.threshold_value,
            "actual_value": e.actual_value,
            "details": e.details,
            "triggered_at": e.triggered_at.isoformat(),
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
            "resolved_by": e.resolved_by,
            "is_active": e.is_active,
        }
        for e in events
    ]


@router.get("/performance")
async def get_performance(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get crypto trading performance summary."""
    cutoff = datetime.utcnow() - timedelta(days=days)

    # All closed orders in the period
    stmt = select(Order).where(
        and_(
            Order.closed_at >= cutoff,
            Order.realised_pnl.is_not(None),
        )
    )
    result = await db.execute(stmt)
    closed_orders = result.scalars().all()

    if not closed_orders:
        # Same shape as the populated response so the frontend never reads undefined
        return {
            "period_days": days,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl_eur": 0.0,
            "win_rate": 0.0,
            "avg_pnl_per_trade": 0.0,
            "best_trade_eur": 0.0,
            "worst_trade_eur": 0.0,
            "max_drawdown_eur": 0.0,
            "max_drawdown_pct": 0.0,
        }

    total_trades = len(closed_orders)
    wins = [o for o in closed_orders if (o.realised_pnl or 0) > 0]
    losses = [o for o in closed_orders if (o.realised_pnl or 0) <= 0]

    total_pnl = sum(o.realised_pnl or 0 for o in closed_orders)
    win_rate = len(wins) / total_trades if total_trades > 0 else 0

    # Simple max drawdown calculation
    cumulative = 0
    peak = 0
    max_drawdown = 0
    for o in sorted(closed_orders, key=lambda x: x.closed_at or datetime.min):
        cumulative += o.realised_pnl or 0
        peak = max(peak, cumulative)
        drawdown = peak - cumulative
        max_drawdown = max(max_drawdown, drawdown)

    total_invested = sum(
        o.order_value_eur or 0 for o in closed_orders if o.side == OrderSide.BUY
    )
    max_dd_pct = (max_drawdown / total_invested * 100) if total_invested > 0 else 0

    return {
        "period_days": days,
        "total_trades": total_trades,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "total_pnl_eur": round(total_pnl, 2),
        "win_rate": round(win_rate, 3),
        "avg_pnl_per_trade": round(total_pnl / total_trades, 2),
        "best_trade_eur": round(max((o.realised_pnl or 0) for o in closed_orders), 2),
        "worst_trade_eur": round(min((o.realised_pnl or 0) for o in closed_orders), 2),
        "max_drawdown_eur": round(max_drawdown, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
    }
