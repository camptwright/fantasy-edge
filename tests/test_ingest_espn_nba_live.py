"""Live canary for ESPN NBA sync - verifies the NBA addition against a real
past game day rather than the current 7-day-ahead window, since the NBA
season doesn't start until 2026-09-30 (no games would be in range right
now). Confirms sync_scoreboard's existing NFL/NCAAF-shaped parsing (season/
week/state mapping, team resolution, score capture) also holds for NBA's
response shape without needing sport-specific code - verified live
2026-09-04 against a real 2026-01-15 slate (Magic 118, Grizzlies 111,
among others)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.ingest.espn import sync_scoreboard
from src.models.facts import Game
from src.models.identity import Team

pytestmark = pytest.mark.live


async def test_nba_scoreboard_creates_final_games_with_scores(db):
    written = await sync_scoreboard(db, sport="nba", dates="20260115")
    assert written >= 0  # odds rows only; games can land with zero odds

    games = (
        await db.scalars(select(Game).where(Game.sport == "nba", Game.espn_event_id.isnot(None)))
    ).all()
    assert len(games) > 0, "ESPN returned no NBA events for 2026-01-15"

    final_games = [g for g in games if g.status == "final"]
    assert final_games, "at least one 2026-01-15 NBA game must already be final"
    assert any(g.home_score is not None and g.away_score is not None for g in final_games)

    teams = await db.scalars(select(Team).where(Team.sport == "nba"))
    assert len(teams.all()) > 0, "NBA teams must resolve through config/team_aliases/nba.yaml"
