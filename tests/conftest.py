"""Test fixtures against a REAL PostgreSQL instance.

Constraint #13: Alembic's --sql offline mode proves the migration code runs,
not that Postgres accepts the DDL. Every schema test here talks to a real
database started by `docker compose up -d postgres`.

The `db` fixture's rollback-after-yield only undoes a test's OWN uncommitted
work. It does nothing about rows a test wrote through code that commits
internally - and every real ingester in this codebase does exactly that
(record_run's `await db.commit()`), by design, to match production
behaviour. Without an explicit reset, every test run permanently writes real
rows into this database and nothing ever cleans them up, so a later test
run's "clean" assertions (e.g. asserting N new rows were written) silently
start depending on whatever a PRIOR run happened to leave behind - a bug
that surfaced empirically as a flaky `written > 0` failure only after
several tasks' tests had accumulated real data here. TRUNCATE at the start
of every test is what actually guarantees isolation.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://fantasy:changeme@localhost:5433/fantasy_edge_test",
)

_TABLES = (
    "quote_availability",
    "teams", "players", "player_external_ids", "games",
    "team_market_lines", "player_prop_lines", "player_game_stats",
    "model_artifacts", "model_predictions", "ingestion_runs",
    "sleeper_leagues", "sleeper_rosters", "sleeper_league_snapshots",
    "team_ratings", "recommendation_snapshots", "calibration_reports",
)


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        # Hold a separate connection for the test's lifetime: ingesters commit
        # internally, so a transaction lock would release too soon. Fail fast
        # rather than truncating a concurrent pytest process's active fixtures.
        async with engine.connect() as guard:
            locked = await guard.scalar(text("SELECT pg_try_advisory_lock(61420921)"))
            if not locked:
                pytest.fail("Another DB test is active; use a separate test database or run serially.")
            async with factory() as reset_session:
                await reset_session.execute(
                    text(f"TRUNCATE TABLE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
                )
                await reset_session.commit()
            async with factory() as session:
                yield session
                await session.rollback()
    finally:
        # NullPool closes the guard connection, releasing its session lock.
        await engine.dispose()
