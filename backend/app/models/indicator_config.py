"""IndicatorConfig model — per-symbol optimised indicator parameters."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IndicatorConfig(Base):
    __tablename__ = "indicator_config"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "indicator_name", name="uq_indicator_config_symbol_indicator"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    indicator_name: Mapped[str] = mapped_column(String(64), nullable=False)

    # JSON-encoded dict of optimal parameters (e.g. {"window": 14, "ema_fast": 12})
    parameters: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    last_optimized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Out-of-sample performance metrics
    oos_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    oos_sortino: Mapped[float | None] = mapped_column(Float, nullable=True)
    oos_return: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<IndicatorConfig {self.symbol}/{self.indicator_name} "
            f"sharpe={self.oos_sharpe}>"
        )
