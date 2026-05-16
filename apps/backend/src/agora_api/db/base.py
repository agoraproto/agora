"""SQLAlchemy base + async session management."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from ..config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            future=True,
            pool_pre_ping=True,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _sessionmaker


def reset_engine_for_tests(new_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    """Test helper: replace the module-level sessionmaker (and skip the real engine)."""
    global _sessionmaker, _engine
    _sessionmaker = new_sessionmaker
    _engine = None  # tests bring their own engine via the new_sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency injection: yield an AsyncSession per request."""
    sm = get_sessionmaker()
    async with sm() as session:
        yield session
