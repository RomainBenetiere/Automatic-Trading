"""SQLAlchemy async engine, session factory, and base model for SQLite."""

from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

is_sqlite = "sqlite" in settings.database_url

connect_args = {}
if is_sqlite:
    connect_args = {
        "check_same_thread": False,
        "timeout": 30.0,
    }

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args=connect_args,
)

if is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency — yields an async DB session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables and run lightweight schema migrations."""
    import logging
    import app.models  # noqa: F401 — register all ORM models on Base.metadata

    _logger = logging.getLogger(__name__)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Lightweight schema migrations for existing SQLite databases
        if "sqlite" in settings.database_url:
            try:
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.execute(text("PRAGMA busy_timeout=30000"))
                await conn.execute(text("PRAGMA synchronous=NORMAL"))
                for table_name in ("positions", "recommendations"):
                    res = await conn.execute(text(f"PRAGMA table_info({table_name})"))
                    columns = [row[1] for row in res.fetchall()]
                    if columns and "account_name" not in columns:
                        await conn.execute(
                            text(f"ALTER TABLE {table_name} ADD COLUMN account_name VARCHAR(128) NOT NULL DEFAULT ''")
                        )

                res = await conn.execute(text("PRAGMA table_info(orders)"))
                columns = [row[1] for row in res.fetchall()]
                if columns and "stop_loss_order_id" not in columns:
                    await conn.execute(
                        text("ALTER TABLE orders ADD COLUMN stop_loss_order_id VARCHAR(128)")
                    )

                # Retroactively apply Bitvavo round-trip execution fee to closed BUY orders that predate fee tracking
                if columns and settings.crypto_fee_pct > 0:
                    fee_rate = settings.crypto_fee_pct / 100.0
                    legacy_orders = (
                        await conn.execute(
                            text(
                                """
                                SELECT id, price, quantity, order_value_eur, realised_pnl, justification
                                FROM orders
                                WHERE closed_at IS NOT NULL
                                  AND realised_pnl IS NOT NULL
                                  AND (justification IS NULL OR justification NOT LIKE '%fee:%')
                                """
                            )
                        )
                    ).fetchall()
                    for row in legacy_orders:
                        oid, px, qty, val_eur, old_pnl, justif = row
                        entry_val = float(val_eur or ((px or 0.0) * (qty or 0.0)))
                        gross_pnl = float(old_pnl or 0.0)
                        exit_val = max(0.0, entry_val + gross_pnl)
                        fee = (entry_val + exit_val) * fee_rate
                        new_pnl = round(gross_pnl - fee, 2)
                        new_justif = f"{justif or ''} (fee: €{fee:.2f})".strip()
                        await conn.execute(
                            text(
                                "UPDATE orders SET realised_pnl = :pnl, justification = :justif WHERE id = :id"
                            ),
                            {"pnl": new_pnl, "justif": new_justif, "id": oid},
                        )

                # Seed indicator_config_history from existing indicator_config rows if history table is empty
                hist_cols = (await conn.execute(text("PRAGMA table_info(indicator_config_history)"))).fetchall()
                cfg_cols = (await conn.execute(text("PRAGMA table_info(indicator_config)"))).fetchall()
                if hist_cols and cfg_cols:
                    hist_count_res = await conn.execute(text("SELECT COUNT(*) FROM indicator_config_history"))
                    hist_count = hist_count_res.scalar() or 0
                    if hist_count == 0:
                        await conn.execute(
                            text(
                                """
                                INSERT INTO indicator_config_history (
                                    symbol, indicator_name, parameters, oos_sharpe, oos_sortino, oos_return, recorded_at
                                )
                                SELECT
                                    symbol,
                                    indicator_name,
                                    parameters,
                                    oos_sharpe,
                                    oos_sortino,
                                    oos_return,
                                    COALESCE(last_optimized_at, updated_at, CURRENT_TIMESTAMP)
                                FROM indicator_config
                                """
                            )
                        )
            except Exception as exc:
                _logger.warning("Non-fatal warning during SQLite migration/seed in init_db: %s", exc)

