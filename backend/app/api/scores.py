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

router = APIRouter(prefix="/api", tags=["scores"])


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

    return [
        {
            "symbol": s.symbol,
            "date": s.date.isoformat(),
            "technical_score": s.technical_score,
            "fundamental_score": s.fundamental_score,
            "dividend_score": s.dividend_score,
            "composite_score": s.composite_score,
            "signal": s.signal,
            "weights_used": s.weights_used,
        }
        for s in scores
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

    return [
        {
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
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get the most recent recommendations."""
    from sqlalchemy import func

    subq = (
        select(Recommendation.symbol, func.max(Recommendation.date).label("max_date"))
        .group_by(Recommendation.symbol)
        .subquery()
    )

    stmt = (
        select(Recommendation)
        .join(
            subq,
            and_(
                Recommendation.symbol == subq.c.symbol,
                Recommendation.date == subq.c.max_date,
            ),
        )
    )

    if account_type:
        stmt = stmt.where(Recommendation.account_type == account_type)

    stmt = stmt.order_by(desc(Recommendation.confidence))

    result = await db.execute(stmt)
    recommendations = result.scalars().all()

    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "date": r.date.isoformat(),
            "account_type": r.account_type,
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
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get historical recommendations."""
    stmt = select(Recommendation).order_by(desc(Recommendation.date))

    if symbol:
        stmt = stmt.where(Recommendation.symbol == symbol)

    stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    recommendations = result.scalars().all()

    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "date": r.date.isoformat(),
            "account_type": r.account_type,
            "action": r.action.value,
            "confidence": r.confidence,
            "narrative": r.narrative,
        }
        for r in recommendations
    ]
