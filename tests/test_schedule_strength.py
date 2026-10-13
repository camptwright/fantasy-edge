"""Strength of schedule: points allowed by position, ranked, mapped to stars."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from src.services import schedule_strength as ss
from src.services.projection_engine import History, PlayerGame


def test_stars_map_rank_to_one_through_five():
    assert (ss.stars(1), ss.stars(32), ss.stars(16.5), ss.stars(None)) == (5, 1, 3, None)


def test_defenses_that_allow_more_rank_first_and_last_season_fills_thin_samples():
    off, soft, hard = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    games, players, positions = {}, {}, {}
    def add(season, defense, pts, n):
        for _ in range(n):
            gid, pid = uuid.uuid4(), uuid.uuid4()
            games[gid] = SimpleNamespace(home_team_id=off, away_team_id=defense, season=season)
            players[(pid, gid)] = PlayerGame(pid, gid, off, datetime(2026, 9, 1, tzinfo=timezone.utc), {"receiving_yards": pts * 10})
            positions[pid] = "WR"
    add(2026, soft, 30, 4)
    add(2026, hard, 5, 2)    # only two games this season ...
    add(2025, hard, 8, 6)    # ... so last season's games fill in
    ranks = ss.allowed_ranks(History(games, {}, players, positions), 2026)
    assert ranks[(soft, "WR")] == 1 and ranks[(hard, "WR")] == 2


def test_relative_stars_spread_teams_into_quintiles():
    values = {i: float(i) for i in range(1, 11)} | {"bye_only": None}
    out = ss.relative_stars(values)
    assert (out[1], out[2], out[3], out[10], out["bye_only"]) == (5, 5, 4, 1, None)
