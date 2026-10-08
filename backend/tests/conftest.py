"""Shared test fixtures.

Environment is set BEFORE any `app` import so settings never touch the real DB/.env.
"""

from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ.setdefault("CRYPTO_LIVE_MODE", "false")
os.environ.setdefault("CRYPTO_GLOBAL_BUDGET_EUR", "1000")
os.environ.setdefault("CRYPTO_PER_TRADE_CAP_PCT", "5")

import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.database import Base  # noqa: E402
import app.models  # noqa: E402,F401  — register all ORM models


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    """Fresh in-memory database per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()
