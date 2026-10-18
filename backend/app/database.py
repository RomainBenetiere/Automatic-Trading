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

