"""ESPN sync against the live endpoint.

Marked `live` because it makes a real network call. Run explicitly with
`pytest -m live`; excluded from the default suite.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.ingest.espn import sync_scoreboard
from src.models.facts import Game
from src.models.governance import IngestionRun

pytestmark = pytest.mark.live


async def test_sync_records_a_run_and_creates_fixtures(db):
    await sync_scoreboard(db, days_ahead=7)

    run = await db.scalar(
        select(IngestionRun).where(IngestionRun.source == "espn").limit(1)
    )
    assert run is not None and run.status == "succeeded"

    games = await db.scalar(
        select(func.count()).select_from(Game).where(Game.espn_event_id.isnot(None))
    )
    assert games > 0, "ESPN returned no events for the next seven days"
