import json
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.indicator_config import IndicatorConfig
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
            "per_trade_cap_pct": settings.crypto_per_trade_cap_pct,
            "stop_loss_pct": settings.crypto_stop_loss_pct,
            "trailing_stop_pct": settings.crypto_trailing_stop_pct,
            "take_profit_pct": settings.crypto_take_profit_pct,
            "circuit_breaker_consecutive_losses": settings.crypto_circuit_breaker_consecutive_losses,
            "circuit_breaker_cumulative_loss_pct": settings.crypto_circuit_breaker_cumulative_loss_pct,
            "circuit_breaker_window_days": settings.crypto_circuit_breaker_window_days,
            "global_budget_eur": settings.crypto_global_budget_eur,
        },
        "weights": {
            "stocks": settings.weights_stocks,
            "etfs": settings.weights_etfs,
            "bonds": settings.weights_bonds,
            "crypto": settings.weights_crypto,
        },
        "schedule": {
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
    """Get optimized indicator parameters per symbol and default regime parameters."""
    stmt = select(IndicatorConfig).order_by(IndicatorConfig.symbol)
    result = await db.execute(stmt)
    configs = result.scalars().all()

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
            "indicator_name": c.indicator_name,
            "parameters": params_dict,
            "last_optimized_at": c.last_optimized_at.isoformat() if c.last_optimized_at else None,
            "oos_sharpe": c.oos_sharpe,
            "oos_sortino": c.oos_sortino,
            "oos_return": c.oos_return,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })

    return {
        "optimized": optimized,
        "defaults": {
            "high_volatility": asdict(PARAMS_HIGH_VOLATILITY),
            "medium_volatility": asdict(PARAMS_MEDIUM_VOLATILITY),
            "low_volatility": asdict(PARAMS_LOW_VOLATILITY),
        },
    }
