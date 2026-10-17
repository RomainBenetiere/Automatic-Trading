"""Scores & recommendation API routes."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.score import Score
from app.models.recommendation import Recommendation
from app.models.position import Position

router = APIRouter(prefix="/api", tags=["scores"])


async def _get_symbol_names(db: AsyncSession) -> dict[str, str]:
    """Fetch symbol-to-name mapping from positions."""
    stmt = select(Position.symbol, Position.name).where(Position.name != "").distinct()
    res = await db.execute(stmt)
    return {row[0]: row[1] for row in res.fetchall()}


# ── Scores ──────────────────────────────────────────────────────────────

@router.get("/scores/latest")
async def get_latest_scores(
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get the latest composite scores for all tracked assets."""
    # Subquery: latest date per symbol
    from sqlalchemy import func

    subq = (
        select(Score.symbol, func.max(Score.date).label("max_date"))
        .group_by(Score.symbol)
        .subquery()
    )

    stmt = (
        select(Score)
        .join(
            subq,
            and_(Score.symbol == subq.c.symbol, Score.date == subq.c.max_date),
        )
        .order_by(desc(Score.composite_score))
    )

    result = await db.execute(stmt)
    scores = result.scalars().all()
    names_map = await _get_symbol_names(db)

    seen = set()
    unique_scores = []
    for s in scores:
        if s.symbol not in seen:
            seen.add(s.symbol)
            unique_scores.append(s)

    return [
        {
            "symbol": s.symbol,
            "name": names_map.get(s.symbol, s.symbol),
            "date": s.date.isoformat() if s.date else "",
            "technical_score": s.technical_score,
            "fundamental_score": s.fundamental_score,
            "dividend_score": s.dividend_score,
            "composite_score": s.composite_score,
            "signal": s.signal,
            "weights_used": s.weights_used,
        }
        for s in unique_scores
    ]


@router.get("/scores/{symbol}/history")
async def get_score_history(
    symbol: str,
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    limit: int = Query(90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get score history for a specific symbol."""
    stmt = select(Score).where(Score.symbol == symbol)

    if from_date:
        stmt = stmt.where(Score.date >= from_date)
    if to_date:
        stmt = stmt.where(Score.date <= to_date)

    stmt = stmt.order_by(desc(Score.date)).limit(limit)

    result = await db.execute(stmt)
    scores = result.scalars().all()
    names_map = await _get_symbol_names(db)

    return [
        {
            "symbol": s.symbol,
            "name": names_map.get(s.symbol, s.symbol),
            "date": s.date.isoformat(),
            "technical_score": s.technical_score,
            "fundamental_score": s.fundamental_score,
            "dividend_score": s.dividend_score,
            "composite_score": s.composite_score,
            "signal": s.signal,
        }
        for s in reversed(scores)  # Return chronologically
    ]


# ── Recommendations ────────────────────────────────────────────────────

@router.get("/recommendations/latest")
async def get_latest_recommendations(
    account_type: str | None = None,
    account_name: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get the most recent recommendations."""
    from sqlalchemy import func

    subq = (
        select(
            Recommendation.symbol,
            Recommendation.account_name,
            func.max(Recommendation.date).label("max_date"),
        )
        .group_by(Recommendation.symbol, Recommendation.account_name)
        .subquery()
    )

    stmt = (
        select(Recommendation)
        .join(
            subq,
            and_(
                Recommendation.symbol == subq.c.symbol,
                Recommendation.account_name == subq.c.account_name,
                Recommendation.date == subq.c.max_date,
            ),
        )
    )

    if account_type:
        stmt = stmt.where(Recommendation.account_type == account_type)
    if account_name:
        stmt = stmt.where(Recommendation.account_name == account_name)

    stmt = stmt.order_by(desc(Recommendation.confidence))

    result = await db.execute(stmt)
    recommendations = result.scalars().all()
    names_map = await _get_symbol_names(db)

    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "name": names_map.get(r.symbol, r.symbol),
            "date": r.date.isoformat(),
            "account_type": r.account_type,
            "account_name": r.account_name,
            "action": r.action.value,
            "confidence": r.confidence,
            "narrative": r.narrative,
            "score_id": r.score_id,
        }
        for r in recommendations
    ]


@router.get("/recommendations/history")
async def get_recommendation_history(
    symbol: str | None = None,
    account_name: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get historical recommendations."""
    stmt = select(Recommendation).order_by(desc(Recommendation.date))

    if symbol:
        stmt = stmt.where(Recommendation.symbol == symbol)
    if account_name:
        stmt = stmt.where(Recommendation.account_name == account_name)

    stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    recommendations = result.scalars().all()
    names_map = await _get_symbol_names(db)

    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "name": names_map.get(r.symbol, r.symbol),
            "date": r.date.isoformat(),
            "account_type": r.account_type,
            "account_name": r.account_name,
            "action": r.action.value,
            "confidence": r.confidence,
            "narrative": r.narrative,
        }
        for r in recommendations
    ]
