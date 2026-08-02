"""Database engine management.

CONSTRAINT #1 - the single most important rule in this codebase.

A pooled asyncpg engine holds live TCP sockets. Celery forks worker processes,
and a forked child inherits those sockets while the parent still believes it
owns them. Two processes then interleave writes on one connection and you get
`InterfaceError: another operation is in progress`, `connection was closed`,
or - worst - silently wrong query results.

So there are two entry points and they are NOT interchangeable:

  API / FastAPI  ->  get_db()          pooled, long-lived, one event loop
  Celery task    ->  get_worker_db()   NullPool, created INSIDE the task

Every Celery task must also use asyncio.run() rather than fetching a loop, so
each task gets a fresh loop that is closed on completion. Reusing a loop across
tasks re-introduces the same cross-process sharing through the back door.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from config.settings import get_settings

# --------------------------------------------------------------- API side ----

_api_engine: AsyncEngine | None = None
_api_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_api_engine() -> AsyncEngine:
    """Pooled engine for the FastAPI process. Never import this into a task."""
    global _api_engine, _api_sessionmaker
    if _api_engine is None:
        settings = get_settings()
        _api_engine = create_async_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=5,
            pool_pre_ping=True,   # survives Postgres restarts
            pool_recycle=1800,
            echo=False,
        )
        _api_sessionmaker = async_sessionmaker(
            _api_engine, class_=AsyncSession, expire_on_commit=False
        )
    return _api_engine


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    get_api_engine()
    assert _api_sessionmaker is not None
    async with _api_sessionmaker() as session:
        yield session


async def dispose_api_engine() -> None:
    """Called from the FastAPI lifespan shutdown hook."""
    global _api_engine, _api_sessionmaker
    if _api_engine is not None:
        await _api_engine.dispose()
        _api_engine = None
        _api_sessionmaker = None


# ------------------------------------------------------------ worker side ----


def make_worker_engine() -> AsyncEngine:
    """A throwaway NullPool engine.

    NullPool opens a connection per checkout and closes it on release, so
    nothing is left in a pool for a forked child to inherit. Must be created
    inside the task body, never at module import time.
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        echo=False,
    )


@asynccontextmanager
async def get_worker_db() -> AsyncIterator[AsyncSession]:
    """Session context manager for Celery tasks.

        @celery_app.task
        def sync_games(sport: str):
            async def _run():
                async with get_worker_db() as db:
                    ...
            asyncio.run(_run())

    The engine is disposed in the finally block so the task leaves no sockets
    behind for the next fork to trip over.
    """
    engine = make_worker_engine()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
