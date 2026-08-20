"""Test fixtures against a REAL PostgreSQL instance.

Constraint #13: Alembic's --sql offline mode proves the migration code runs,
not that Postgres accepts the DDL. Every schema test here talks to a real
database started by `docker compose up -d postgres`.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://fantasy:changeme@localhost:5433/fantasy_edge_test",
)


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
            await session.rollback()
    finally:
        await engine.dispose()
