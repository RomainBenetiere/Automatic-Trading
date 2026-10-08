"""Portfolio / position API routes."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.collectors.ghostfolio import GhostfolioClient
from app.models.position import Position, AssetType, AccountType

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/positions")
async def get_positions(
    account_type: str | None = None,
    asset_type: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get current positions, optionally filtered by account/asset type."""
    # Get the latest snapshot date
    latest_date_stmt = select(Position.snapshot_date).order_by(
        desc(Position.snapshot_date)
    ).limit(1)
    result = await db.execute(latest_date_stmt)
    latest_date = result.scalar_one_or_none()

    if not latest_date:
        return []

    stmt = select(Position).where(Position.snapshot_date == latest_date)
    if account_type:
        stmt = stmt.where(Position.account_type == account_type)
    if asset_type:
        stmt = stmt.where(Position.asset_type == asset_type)

    stmt = stmt.order_by(Position.symbol)
    result = await db.execute(stmt)
    positions = result.scalars().all()

    return [
        {
            "id": p.id,
            "symbol": p.symbol,
            "name": p.name,
            "asset_type": p.asset_type.value,
            "account_type": p.account_type.value,
            "quantity": p.quantity,
            "avg_cost": p.avg_cost,
            "current_price": p.current_price,
            "currency": p.currency,
            "market_value": p.market_value,
            "unrealised_pnl": p.unrealised_pnl,
            "snapshot_date": p.snapshot_date.isoformat(),
        }
        for p in positions
    ]


@router.get("/positions/{symbol}")
async def get_position_detail(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get detailed position info for a single symbol."""
    stmt = (
        select(Position)
        .where(Position.symbol == symbol)
        .order_by(desc(Position.snapshot_date))
        .limit(1)
    )
    result = await db.execute(stmt)
    position = result.scalar_one_or_none()

    if not position:
        raise HTTPException(status_code=404, detail=f"Position not found: {symbol}")

    return {
        "id": position.id,
        "symbol": position.symbol,
        "name": position.name,
        "asset_type": position.asset_type.value,
        "account_type": position.account_type.value,
        "quantity": position.quantity,
        "avg_cost": position.avg_cost,
        "current_price": position.current_price,
        "currency": position.currency,
        "market_value": position.market_value,
        "unrealised_pnl": position.unrealised_pnl,
        "snapshot_date": position.snapshot_date.isoformat(),
    }


@router.post("/sync")
async def sync_positions(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Trigger a manual Ghostfolio sync (replaces today's snapshot)."""
    client = GhostfolioClient()
    try:
        holdings = await client.get_holdings()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ghostfolio sync failed: {e}")
    finally:
        await client.close()

    await db.execute(delete(Position).where(Position.snapshot_date == date.today()))
    for h in holdings:
        db.add(Position(**h))
    await db.commit()
    return {"status": "ok", "synced": len(holdings)}
