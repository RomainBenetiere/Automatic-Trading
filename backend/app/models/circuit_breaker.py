"""CircuitBreakerEvent model — history of automatic trading pauses."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CircuitBreakerEvent(Base):
    __tablename__ = "circuit_breaker_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger_reason: Mapped[str] = mapped_column(
        String(64), nullable=False
    )  # "consecutive_losses" | "cumulative_loss" | "manual"

    # What threshold was exceeded
    threshold_value: Mapped[float] = mapped_column(Float, nullable=False)
    actual_value: Mapped[float] = mapped_column(Float, nullable=False)

    # Additional context
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    triggered_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # "manual" | "auto" | "timeout"

    def __repr__(self) -> str:
        status = "ACTIVE" if self.resolved_at is None else "RESOLVED"
        return (
            f"<CircuitBreakerEvent [{status}] {self.trigger_reason} "
            f"actual={self.actual_value} > threshold={self.threshold_value}>"
        )

    @property
    def is_active(self) -> bool:
        """Return True if this circuit breaker event has not been resolved."""
        return self.resolved_at is None
