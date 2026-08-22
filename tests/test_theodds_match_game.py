"""_match_game must never misattribute odds to the wrong season's Game row.

Division rivals play the same home/away arrangement every season, so a
team-pair match alone is not enough: if a new season's odds event arrives
before that season's Game row exists locally (e.g. odds polling running
ahead of the ESPN/nflverse schedule sync), and the only existing candidate
for that team pair is a prior season's fixture, blindly trusting a single
candidate would silently write current lines onto a historical game.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.ingest.identity import resolve_team
from src.ingest.theodds import _match_game
from src.models.facts import Game

KICKOFF = datetime(2026, 9, 10, 0, 15, tzinfo=timezone.utc)
EVENT = {
    "home_team": "Seattle Seahawks",
    "away_team": "New England Patriots",
    "commence_time": "2026-09-10T00:15:00Z",
}


async def _teams(db):
    home = await resolve_team(db, "Seattle Seahawks")
    away = await resolve_team(db, "New England Patriots")
    await db.flush()
    return home, away


async def test_single_candidate_with_matching_time_is_matched(db):
    home, away = await _teams(db)
    game = Game(
        season=2026, week=1, status="scheduled",
        home_team_id=home.id, away_team_id=away.id, game_time=KICKOFF,
    )
    db.add(game)
    await db.flush()

    matched = await _match_game(db, EVENT)
    assert matched is not None
    assert matched.id == game.id


async def test_single_candidate_with_mismatched_time_is_not_matched(db):
    home, away = await _teams(db)
    # Same team pair, prior season - far outside the 24h match window.
    stale_game = Game(
        season=2024, week=1, status="final",
        home_team_id=home.id, away_team_id=away.id,
        game_time=KICKOFF - timedelta(days=730),
    )
    db.add(stale_game)
    await db.flush()

    matched = await _match_game(db, EVENT)
    assert matched is None


async def test_single_candidate_with_unknown_time_is_matched(db):
    home, away = await _teams(db)
    game = Game(
        season=2026, week=1, status="scheduled",
        home_team_id=home.id, away_team_id=away.id, game_time=None,
    )
    db.add(game)
    await db.flush()

    matched = await _match_game(db, EVENT)
    assert matched is not None
    assert matched.id == game.id


async def test_multiple_candidates_returns_the_one_inside_the_window(db):
    home, away = await _teams(db)
    stale_game = Game(
        season=2024, week=1, status="final",
        home_team_id=home.id, away_team_id=away.id,
        game_time=KICKOFF - timedelta(days=730),
    )
    current_game = Game(
        season=2026, week=1, status="scheduled",
        home_team_id=home.id, away_team_id=away.id, game_time=KICKOFF,
    )
    db.add_all([stale_game, current_game])
    await db.flush()

    matched = await _match_game(db, EVENT)
    assert matched is not None
    assert matched.id == current_game.id
