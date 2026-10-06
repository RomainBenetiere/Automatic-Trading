"""Score model — technical / fundamental / dividend / composite score per asset and date."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_scores_symbol_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    technical_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fundamental_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    dividend_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # JSON-encoded weights used: e.g. {"technical": 0.4, "fundamental": 0.35, "dividend": 0.25}
    weights_used: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # Action signal derived from composite score
    signal: Mapped[str | None] = mapped_column(String(16), nullable=True)  # strong_buy / buy / hold / reduce / sell

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<Score {self.symbol} @ {self.date} "
            f"composite={self.composite_score} signal={self.signal}>"
        )
