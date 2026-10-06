"""Recommendation model — generated advisory recommendations per asset."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ActionType(str, enum.Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    REDUCE = "reduce"
    SELL = "sell"


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)  # brokerage / pea / assurance_vie / per
    action: Mapped[ActionType] = mapped_column(Enum(ActionType), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # LLM-generated narrative justifying the recommendation
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Link back to the score that produced this recommendation
    score_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("scores.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<Recommendation {self.symbol} {self.action.value} "
            f"confidence={self.confidence:.0%} @ {self.date}>"
        )
