"""Position model — periodic snapshot of holdings from Ghostfolio / Bitvavo."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AssetType(str, enum.Enum):
    STOCK = "stock"
    ETF = "etf"
    BOND = "bond"
    CRYPTO = "crypto"


class AccountType(str, enum.Enum):
    BROKERAGE = "brokerage"
    PEA = "pea"
    ASSURANCE_VIE = "assurance_vie"
    PER = "per"
    CRYPTO = "crypto"


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(Enum(AccountType), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_cost: Mapped[float] = mapped_column(Float, nullable=True)
    current_price: Mapped[float] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="EUR")
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<Position {self.symbol} qty={self.quantity} "
            f"account={self.account_type.value} @ {self.snapshot_date}>"
        )

    @property
    def market_value(self) -> float | None:
        """Current market value of the position."""
        if self.current_price is not None:
            return self.quantity * self.current_price
        return None

    @property
    def unrealised_pnl(self) -> float | None:
        """Unrealised profit/loss based on avg cost."""
        if self.current_price is not None and self.avg_cost is not None:
            return self.quantity * (self.current_price - self.avg_cost)
        return None
