"""Audit wrapper for every ingestion job.

Data freshness and model calibration are separate questions. Recording runs
here is what lets health reporting say "the odds feed is stale" without
implying "the model is broken".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.base import utcnow
from src.models.governance import IngestionRun


@asynccontextmanager
async def record_run(db: AsyncSession, source: str) -> AsyncIterator[IngestionRun]:
    run = IngestionRun(source=source, status="running")
    db.add(run)
    await db.flush()
    try:
        yield run
    except Exception as exc:
        run.status = "failed"
        run.detail = f"{type(exc).__name__}: {exc}"[:2000]
        run.finished_at = utcnow()
        await db.commit()
        raise
    run.status = "succeeded"
    run.finished_at = utcnow()
    await db.commit()
