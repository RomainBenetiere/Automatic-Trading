import json
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.indicator_config import IndicatorConfig, IndicatorConfigHistory
from app.models.position import Position
from app.analysis.technical import (
    PARAMS_HIGH_VOLATILITY,
    PARAMS_MEDIUM_VOLATILITY,
    PARAMS_LOW_VOLATILITY,
)

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config() -> dict[str, Any]:
    """Get current runtime configuration (secrets redacted)."""
    return {
        "mode": "live" if settings.crypto_live_mode else "paper",
        "crypto_basket": settings.crypto_basket_list,
        "guardrails": {
            "fee_pct": settings.crypto_fee_pct,
            "buy_pct": settings.crypto_buy_pct,
            "strong_buy_pct": settings.crypto_strong_buy_pct,
            "per_trade_cap_pct": settings.crypto_per_trade_cap_pct,
            "stop_loss_pct": settings.crypto_stop_loss_pct,
            "trailing_stop_pct": settings.crypto_trailing_stop_pct,
            "take_profit_pct": settings.crypto_take_profit_pct,
            "circuit_breaker_consecutive_losses": settings.crypto_circuit_breaker_consecutive_losses,
            "circuit_breaker_cumulative_loss_pct": settings.crypto_circuit_breaker_cumulative_loss_pct,
            "circuit_breaker_window_days": settings.crypto_circuit_breaker_window_days,
            "global_budget_eur": settings.crypto_global_budget_eur,
            "buy_cooldown_days": settings.crypto_buy_cooldown_days,
            "max_allocation_pct": settings.crypto_max_allocation_pct,
        },
        "weights": {
            "stocks": settings.weights_stocks,
            "etfs": settings.weights_etfs,
            "bonds": settings.weights_bonds,
            "crypto": settings.weights_crypto,
        },
        "schedule": {
            "crypto_candle_interval": settings.crypto_candle_interval,
            "crypto_strategy_hours": settings.crypto_strategy_cron_hours,
            "crypto_stops_minutes": settings.crypto_stops_check_cron_minutes,
            "crypto_hour": settings.crypto_schedule_hour,
            "crypto_minute": settings.crypto_schedule_minute,
            "stocks_day": settings.stocks_schedule_day_of_week,
            "stocks_hour": settings.stocks_schedule_hour,
            "stocks_minute": settings.stocks_schedule_minute,
        },
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "synthesis_language": settings.synthesis_language,
        # "configured" = a credential is set; live connectivity is reported by /api/health
        "services": {
            "ghostfolio_url": settings.ghostfolio_url,
            "ghostfolio_configured": bool(settings.ghostfolio_token),
            "market_data_provider": settings.market_data_provider,
            "fmp_configured": bool(settings.fmp_api_key),
            "bitvavo_configured": bool(settings.bitvavo_api_key),
            "llm_configured": bool(
                {
                    "gemini": settings.gemini_api_key,
                    "openai": settings.openai_api_key,
                    "anthropic": settings.anthropic_api_key,
                }.get(settings.llm_provider)
            ),
        },
    }


@router.get("/indicators")
async def get_indicator_configs(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get optimized indicator parameters per symbol, 3-month history, and default regime parameters."""
    stmt = select(IndicatorConfig).order_by(IndicatorConfig.symbol)
    result = await db.execute(stmt)
    configs = result.scalars().all()

    pos_stmt = select(Position.symbol, Position.name).where(Position.name != "").distinct()
    pos_res = await db.execute(pos_stmt)
    names_map = {row[0]: row[1] for row in pos_res.fetchall()}

    optimized = []
    for c in configs:
        params_dict = {}
        if c.parameters:
            try:
                params_dict = json.loads(c.parameters)
            except Exception:
                params_dict = {}
        optimized.append({
            "id": c.id,
            "symbol": c.symbol,
            "name": names_map.get(c.symbol, c.symbol),
            "indicator_name": c.indicator_name,
            "parameters": params_dict,
            "last_optimized_at": c.last_optimized_at.isoformat() if c.last_optimized_at else None,
            "oos_sharpe": c.oos_sharpe,
            "oos_sortino": c.oos_sortino,
            "oos_return": c.oos_return,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })

    # 3-month (90-day) history ordered newest first
    cutoff_90d = datetime.utcnow() - timedelta(days=90)
    hist_stmt = (
        select(IndicatorConfigHistory)
        .where(IndicatorConfigHistory.recorded_at >= cutoff_90d)
        .order_by(desc(IndicatorConfigHistory.recorded_at))
        .limit(500)
    )
    hist_res = await db.execute(hist_stmt)
    hist_rows = hist_res.scalars().all()

    history = []
    for h in hist_rows:
        h_params = {}
        if h.parameters:
            try:
                h_params = json.loads(h.parameters)
            except Exception:
                h_params = {}
        history.append({
            "id": h.id,
            "symbol": h.symbol,
            "name": names_map.get(h.symbol, h.symbol),
            "indicator_name": h.indicator_name,
            "parameters": h_params,
            "oos_sharpe": h.oos_sharpe,
            "oos_sortino": h.oos_sortino,
            "oos_return": h.oos_return,
            "recorded_at": h.recorded_at.isoformat() if h.recorded_at else None,
        })

    return {
        "optimized": optimized,
        "history": history,
        "default_weights": settings.technical_weights,
        "defaults": {
            "high_volatility": asdict(PARAMS_HIGH_VOLATILITY),
            "medium_volatility": asdict(PARAMS_MEDIUM_VOLATILITY),
            "low_volatility": asdict(PARAMS_LOW_VOLATILITY),
        },
    }


@router.get("/indicators/history")
async def get_indicator_config_history(
    symbol: str | None = Query(None),
    days: int = Query(90, ge=1, le=365),
    limit: int = Query(300, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get historical indicator windows and weights over the last N days (default 90 days / 3 months)."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    stmt = select(IndicatorConfigHistory).where(IndicatorConfigHistory.recorded_at >= cutoff)
    if symbol:
        stmt = stmt.where(IndicatorConfigHistory.symbol == symbol)
    stmt = stmt.order_by(desc(IndicatorConfigHistory.recorded_at)).limit(limit)

    res = await db.execute(stmt)
    rows = res.scalars().all()

    pos_stmt = select(Position.symbol, Position.name).where(Position.name != "").distinct()
    pos_res = await db.execute(pos_stmt)
    names_map = {row[0]: row[1] for row in pos_res.fetchall()}

    history = []
    for h in rows:
        h_params = {}
        if h.parameters:
            try:
                h_params = json.loads(h.parameters)
            except Exception:
                h_params = {}
        history.append({
            "id": h.id,
            "symbol": h.symbol,
            "name": names_map.get(h.symbol, h.symbol),
            "indicator_name": h.indicator_name,
            "parameters": h_params,
            "oos_sharpe": h.oos_sharpe,
            "oos_sortino": h.oos_sortino,
            "oos_return": h.oos_return,
            "recorded_at": h.recorded_at.isoformat() if h.recorded_at else None,
        })
    return history

