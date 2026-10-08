"""Health / status endpoint."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter

from app.collectors.bitvavo import BitvavoClient
from app.collectors.fmp import FMPClient
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

    # Check FMP
    try:
        fmp = FMPClient()
        fmp_ok = await fmp.health_check()
        await fmp.close()
        status["services"]["fmp"] = {
            "status": "connected" if fmp_ok else "unreachable",
        }
        if not fmp_ok and getattr(fmp, "last_error", None):
            status["services"]["fmp"]["error"] = fmp.last_error
    except Exception as e:
        status["services"]["fmp"] = {"status": "error", "error": str(e)}

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
