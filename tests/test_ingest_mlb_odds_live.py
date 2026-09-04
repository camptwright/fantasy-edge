"""Live canary proving the full MLB pipeline - MLB Stats API schedule ->
team resolution -> Pinnacle/Bovada odds matching - actually converges on
real games, not just that each piece works in isolation. Unlike NBA (off-
season, verified against a historical date instead), MLB is in-season right
now, so this can assert against the live forward-looking window directly."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.ingest.bovada import poll_team_markets as poll_bovada
from src.ingest.mlb import sync_schedule
from src.ingest.pinnacle import poll_team_markets as poll_pinnacle
from src.models.facts import TeamMarketLine

pytestmark = pytest.mark.live


async def test_mlb_schedule_and_odds_converge_on_the_same_games(db):
    games_written = await sync_schedule(db, days_ahead=3)
    assert games_written > 0, "MLB Stats API returned no games in the next 3 days"

    pinnacle_written = await poll_pinnacle(db, sport="mlb")
    bovada_written = await poll_bovada(db, sport="mlb")
    assert pinnacle_written > 0, "Pinnacle returned no matchable MLB lines"
    assert bovada_written > 0, "Bovada returned no matchable MLB lines"

    sources = {
        row[0]
        for row in await db.execute(
            select(TeamMarketLine.source).where(TeamMarketLine.source.in_(("pinnacle", "bovada")))
        )
    }
    assert sources == {"pinnacle", "bovada"}
