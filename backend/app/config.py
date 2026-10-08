"""Application configuration — loaded from environment variables / .env file."""

from __future__ import annotations

from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the entire application.

    All values can be overridden via environment variables or a `.env` file
    located at the project root (one level above `backend/`).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Ghostfolio ──────────────────────────────────────────────────────
    ghostfolio_url: str = "http://localhost:3333"
    ghostfolio_token: str = ""

    # ── Financial Modeling Prep ──────────────────────────────────────────
    fmp_api_key: str = ""

    # ── Bitvavo ─────────────────────────────────────────────────────────
    bitvavo_api_key: str = ""
    bitvavo_api_secret: str = ""

    # ── LLM ─────────────────────────────────────────────────────────────
    llm_provider: str = Field(default="gemini", pattern=r"^(gemini|openai|anthropic)$")
    llm_model: str = "gemini-2.5-flash"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # ── Database ────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/trading.db"

    # ── Crypto guardrails ───────────────────────────────────────────────
    crypto_per_trade_cap_pct: float = Field(default=5.0, ge=0.1, le=100.0)
    crypto_stop_loss_pct: float = Field(default=5.0, ge=0.1, le=50.0)
    crypto_trailing_stop_pct: float = Field(default=3.0, ge=0.1, le=50.0)
    crypto_take_profit_pct: float = Field(default=15.0, ge=1.0, le=500.0)
    crypto_circuit_breaker_consecutive_losses: int = Field(default=3, ge=1, le=20)
    crypto_circuit_breaker_cumulative_loss_pct: float = Field(default=15.0, ge=1.0, le=100.0)
    crypto_circuit_breaker_window_days: int = Field(default=7, ge=1, le=90)
    crypto_global_budget_eur: float = Field(default=1000.0, ge=0.0)
    crypto_buy_cooldown_days: int = Field(default=3, ge=0, le=30)
    crypto_max_allocation_pct: float = Field(default=20.0, ge=1.0, le=100.0)

    # ── Crypto basket ───────────────────────────────────────────────────
    crypto_basket: str = "BTC-EUR,ETH-EUR,SOL-EUR,XRP-EUR,ADA-EUR"

    @property
    def crypto_basket_list(self) -> list[str]:
        """Return the crypto basket as a list of market pairs."""
        return [s.strip() for s in self.crypto_basket.split(",") if s.strip()]

    # ── Paper trading ───────────────────────────────────────────────────
    crypto_live_mode: bool = False
    paper_trading_start_date: str = ""

    # ── Scheduler (UTC) ─────────────────────────────────────────────────
    crypto_schedule_hour: int = Field(default=8, ge=0, le=23)
    crypto_schedule_minute: int = Field(default=0, ge=0, le=59)
    stocks_schedule_day_of_week: str = "sun"
    stocks_schedule_hour: int = Field(default=20, ge=0, le=23)
    stocks_schedule_minute: int = Field(default=0, ge=0, le=59)

    # ── Score weights ───────────────────────────────────────────────────
    weights_stocks: str = "40,35,25"
    weights_etfs: str = "35,30,35"
    weights_bonds: str = "20,30,50"
    weights_crypto: str = "100,0,0"

    # ── Synthesis language ──────────────────────────────────────────────
    synthesis_language: str = Field(default="fr", pattern=r"^(fr|en)$")

    # ── Helpers ─────────────────────────────────────────────────────────

    def get_weights(self, asset_type: str) -> tuple[float, float, float]:
        """Return (technical, fundamental, dividend) weights for an asset type.

        Weights are normalised so they sum to 1.0.
        """
        raw = {
            "stock": self.weights_stocks,
            "etf": self.weights_etfs,
            "bond": self.weights_bonds,
            "crypto": self.weights_crypto,
        }.get(asset_type, self.weights_stocks)

        parts = [float(x) for x in raw.split(",")]
        if len(parts) != 3:
            parts = [40.0, 35.0, 25.0]

        total = sum(parts)
        if total == 0:
            return (1 / 3, 1 / 3, 1 / 3)
        return (parts[0] / total, parts[1] / total, parts[2] / total)

    @field_validator("database_url")
    @classmethod
    def ensure_data_directory(cls, v: str) -> str:
        """Create the data directory for SQLite if it doesn't exist."""
        if "sqlite" in v:
            # Extract the file path from the SQLAlchemy URL
            path_part = v.split("///")[-1]
            db_path = Path(path_part)
            db_path.parent.mkdir(parents=True, exist_ok=True)
        return v


# Singleton — import this across the app
settings = Settings()
