"""Runtime configuration API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.config import settings

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
        "services": {
            "ghostfolio_url": settings.ghostfolio_url,
            "ghostfolio_connected": bool(settings.ghostfolio_token),
            "fmp_connected": bool(settings.fmp_api_key),
            "bitvavo_connected": bool(settings.bitvavo_api_key),
            "gemini_connected": bool(settings.gemini_api_key),
        },
    }
