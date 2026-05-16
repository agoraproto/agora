"""Pytest fixtures: in-memory SQLite per test, FastAPI TestClient wired to it."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from agora_api.db.base import Base, get_session, reset_engine_for_tests
from agora_api.main import app


@pytest_asyncio.fixture
async def db_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Fresh in-memory SQLite per test, schema migrated via Base.metadata."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    reset_engine_for_tests(sm)
    try:
        yield sm
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with db_sessionmaker() as s:
        yield s


@pytest_asyncio.fixture
async def client(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """FastAPI TestClient with DB dependency overridden to use the test sessionmaker."""

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with db_sessionmaker() as s:
            yield s

    app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
