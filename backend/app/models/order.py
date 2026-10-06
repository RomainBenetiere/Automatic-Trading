"""Order model — crypto orders (paper or real) with full justification and status tracking."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OrderSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, enum.Enum):
    PAPER = "paper"
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # fill price
    order_value_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), nullable=False)
    paper_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Justification
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON snapshot of the signals that triggered this order
    signals_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Risk management
    stop_loss_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trailing_stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    highest_price_since_entry: Mapped[float | None] = mapped_column(Float, nullable=True)

    # External exchange order ID (for live orders)
    exchange_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # P&L tracking
    realised_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        mode = "PAPER" if self.paper_mode else "LIVE"
        return (
            f"<Order [{mode}] {self.side.value} {self.quantity} {self.symbol} "
            f"status={self.status.value}>"
        )
