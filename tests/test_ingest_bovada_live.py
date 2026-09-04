"""Live canary for src/ingest/bovada.py - Bovada's coupon JSON is
undocumented and can change shape without notice, which a fixture-based
test cannot catch."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.ingest.bovada import poll_team_markets
from src.ingest.espn import sync_scoreboard
from src.models.facts import TeamMarketLine

pytestmark = pytest.mark.live


async def test_nfl_markets_are_written_against_live_espn_seeded_games(db):
    await sync_scoreboard(db, sport="nfl", days_ahead=14)
    written = await poll_team_markets(db, sport="nfl")
    assert written > 0, "Bovada returned no matchable NFL lines"

    # sync_scoreboard (ESPN) also writes its own team_market_lines rows
    # (source="espn") - scope the count to this source's own rows, not the
    # whole append-only table.
    rows = await db.scalar(
        select(func.count()).select_from(TeamMarketLine).where(TeamMarketLine.source == "bovada")
    )
    assert rows == written

    markets = {
        row[0]
        for row in await db.execute(
            select(TeamMarketLine.market).where(TeamMarketLine.source == "bovada").distinct()
        )
    }
    assert markets <= {"moneyline", "spread", "total"}
