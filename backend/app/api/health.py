"""Health / status endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter

from app.collectors.bitvavo import BitvavoClient
from app.collectors.yahoo import get_market_data_client
from app.collectors.ghostfolio import GhostfolioClient
from app.config import settings

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def health_check() -> dict[str, Any]:
    """Service health check with API connectivity status."""
    status: dict[str, Any] = {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "mode": "live" if settings.crypto_live_mode else "paper",
        "services": {},
    }

    # Check Ghostfolio
    try:
        gf = GhostfolioClient()
        gf_ok = await gf.health_check()
        await gf.close()
        status["services"]["ghostfolio"] = {
            "status": "connected" if gf_ok else "unreachable",
            "url": settings.ghostfolio_url,
        }
    except Exception as e:
        status["services"]["ghostfolio"] = {"status": "error", "error": str(e)}

    # Check market data provider (Yahoo Finance or FMP)
    service_key = "fmp" if settings.market_data_provider.lower() == "fmp" else "yahoo_finance"
    try:
        md = get_market_data_client()
        md_ok = await md.health_check()
        await md.close()
        status["services"][service_key] = {
            "status": "connected" if md_ok else "unreachable",
        }
        if not md_ok and getattr(md, "last_error", None):
            status["services"][service_key]["error"] = md.last_error
    except Exception as e:
        status["services"][service_key] = {"status": "error", "error": str(e)}

    # Check Bitvavo
    try:
        bv = BitvavoClient()
        bv_ok = bv.health_check()
        status["services"]["bitvavo"] = {
            "status": "connected" if bv_ok else "unreachable",
        }
    except Exception as e:
        status["services"]["bitvavo"] = {"status": "error", "error": str(e)}

    # Overall status
    all_ok = all(
        s.get("status") == "connected"
        for s in status["services"].values()
    )
    status["status"] = "ok" if all_ok else "degraded"

    return status
