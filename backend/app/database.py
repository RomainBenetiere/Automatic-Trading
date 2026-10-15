"""SQLAlchemy async engine, session factory, and base model for SQLite."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    # SQLite-specific: allow async usage and disable check_same_thread
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Lightweight schema migrations for existing SQLite databases
        if "sqlite" in settings.database_url:
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
