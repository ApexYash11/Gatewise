"""Engine and session helpers.

SQLite is the default because it needs no server, so a clean clone runs. The
models use portable SQLAlchemy types, so the same code runs against PostgreSQL by
changing ``DATABASE_URL`` and nothing else.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

DEFAULT_URL = "sqlite+aiosqlite:///./gatewise.db"


def create_engine(url: str = DEFAULT_URL) -> AsyncEngine:
    """Create an async engine with schema creation wired to first use."""
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_async_engine(url, echo=False, connect_args=connect_args)


async def create_schema(engine: AsyncEngine) -> None:
    """Create tables that do not yet exist. Safe to call repeatedly."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session_scope(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Yield a session, committing on success and rolling back on error."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
