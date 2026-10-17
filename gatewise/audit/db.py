"""Engine and session helpers.

SQLite is the default because it needs no server, so a clean clone runs. The
models use portable SQLAlchemy types, so the same code runs against PostgreSQL by
changing ``DATABASE_URL`` and nothing else.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import AsyncIterator

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base

DEFAULT_URL = "sqlite+aiosqlite:///./gatewise.db"

#: Columns added after an audit database was first created. ``create_all``
#: never alters existing tables, so older databases need this explicit,
#: idempotent upgrade before the claim machinery can touch them.
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("actions", "claimed_at", "TIMESTAMP"),
    ("actions", "claim_token", "VARCHAR(64)"),
)


def create_engine(url: str = DEFAULT_URL) -> AsyncEngine:
    """Create an async engine with schema creation wired to first use."""
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_async_engine(url, echo=False, connect_args=connect_args)


async def create_schema(engine: AsyncEngine) -> None:
    """Create tables that do not yet exist, and upgrade existing ones.

    Safe to call repeatedly. New tables come from ``create_all``; new columns
    are added with guarded ``ALTER TABLE ADD COLUMN``, which PostgreSQL and
    SQLite both accept for nullable columns with no default -- exactly what
    the claim columns are. Existing audit data is never dropped or rewritten.
    A table that did not exist before is skipped here: ``create_all`` creates
    it complete, migrations like these only exist for tables that predate the
    columns.
    """
    async with engine.begin() as connection:
        existing = await connection.run_sync(_columns_by_table)
        await connection.run_sync(Base.metadata.create_all)
        for table, column, column_type in _MIGRATIONS:
            if table not in existing:
                continue
            if column in existing[table]:
                continue
            try:
                await connection.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {column} {column_type} NULL"
                )
            except SQLAlchemyError as exc:
                # Two workers can upgrade the same old database: both see the
                # column missing, the loser's ALTER fails with the duplicate
                # error. That outcome *is* the successful migration, so it is
                # tolerated; anything else propagates and aborts startup
                # visibly.
                message = str(exc).lower()
                if (
                    "duplicate column" not in message
                    and "already exists" not in message
                ):
                    raise
        # Legacy rows already mid-execution at upgrade time have a NULL claim
        # time, so the stale-reclaim predicate would never match and they
        # could never be retried. Stamp them now: they become reclaimable
        # after the staleness window instead of being trapped forever. The
        # timestamp is a bound, UTC-naive value, because `CURRENT_TIMESTAMP`
        # is the session's wall time on PostgreSQL and would shift the
        # reclaim window by the database's timezone offset.
        await connection.execute(
            text(
                "UPDATE actions SET claimed_at = :now "
                "WHERE status = 'executing' AND claimed_at IS NULL"
            ),
            {"now": datetime.now(UTC).replace(tzinfo=None)},
        )


def _columns_by_table(sync_connection: Connection) -> dict[str, set[str]]:
    """Snapshot of every table and its columns, taken before ``create_all``."""
    inspector = inspect(sync_connection)
    return {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in inspector.get_table_names()
    }


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
