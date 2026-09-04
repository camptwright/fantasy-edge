"""NHL API sync (src/ingest/nhl.py): offline unit tests against fake game
payloads shaped like the real API, plus one live smoke test.

Real shape verified live 2026-09-04 against api-web.nhle.com/v1/schedule -
both a Final 2026-01-15 game and a real June (playoff, gameType 3) game.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.ingest.identity import resolve_team
from src.ingest.nhl import _upsert_game, sync_schedule
from src.models.facts import Game
from src.models.ratings import TeamRating


def _fake_game(
    game_id: int = 2025020740,
    home: str = "BUF",
    away: str = "MTL",
    home_score: int | None = 5,
    away_score: int | None = 3,
    state: str = "OFF",
    game_type: int = 2,
    season: int = 20252026,
    start_time_utc: str = "2026-01-16T00:00:00Z",
) -> dict:
    return {
        "id": game_id,
        "season": season,
        "gameType": game_type,
        "startTimeUTC": start_time_utc,
        "gameState": state,
        "homeTeam": {"abbrev": home, "score": home_score},
        "awayTeam": {"abbrev": away, "score": away_score},
    }


class _Run:
    def __init__(self):
        self.detail = None


async def test_upsert_game_creates_a_final_game_with_scores(db):
    touched = await _upsert_game(db, _fake_game(), _Run())
    assert touched is True

    game = await db.scalar(select(Game).where(Game.nhl_game_id == "2025020740"))
    assert game is not None
    assert game.sport == "nhl"
    assert game.status == "final"
    assert game.home_score == 5
    assert game.away_score == 3
    assert game.game_type == "REG"
    # Season stored as the start year of the two-year NHL convention.
    assert game.season == 2025


async def test_upsert_game_maps_future_and_playoff_state(db):
    game = _fake_game(
        game_id=999001, state="FUT", game_type=3,
        home_score=None, away_score=None,
    )
    touched = await _upsert_game(db, game, _Run())
    assert touched is True

    row = await db.scalar(select(Game).where(Game.nhl_game_id == "999001"))
    assert row.status == "scheduled"
    assert row.game_type == "POST"  # playoffs collapse to POST, not invented rounds
    assert row.home_score is None


async def test_upsert_game_is_idempotent_on_game_id(db):
    await _upsert_game(db, _fake_game(), _Run())
    await _upsert_game(db, _fake_game(home_score=9), _Run())

    rows = (await db.execute(select(Game).where(Game.nhl_game_id == "2025020740"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].home_score == 9


async def test_elo_updates_exactly_once_when_a_game_first_goes_final(db):
    game = _fake_game(state="FUT", home_score=None, away_score=None)
    await _upsert_game(db, game, _Run())
    await db.commit()

    home = await resolve_team(db, "BUF", sport="nhl")
    rating_before = await db.scalar(select(TeamRating).where(TeamRating.team_id == home.id))
    assert rating_before is None

    await _upsert_game(db, _fake_game(state="OFF"), _Run())
    await db.commit()
    rating_after_first = await db.scalar(select(TeamRating).where(TeamRating.team_id == home.id))
    assert rating_after_first is not None

    await _upsert_game(db, _fake_game(state="OFF"), _Run())
    await db.commit()
    rating_after_second = await db.scalar(select(TeamRating).where(TeamRating.team_id == home.id))
    assert rating_after_second.rating == rating_after_first.rating


async def test_unresolvable_team_is_parked_not_raised(db):
    game = _fake_game(home="ZZZ", game_id=999002)
    touched = await _upsert_game(db, game, _Run())
    assert touched is False

    row = await db.scalar(select(Game).where(Game.nhl_game_id == "999002"))
    assert row is None


@pytest.mark.live
async def test_live_schedule_creates_final_games_with_scores(db):
    written = await sync_schedule(db, start_date="2026-01-12", days_ahead=7)
    assert written > 0

    games = (await db.scalars(select(Game).where(Game.sport == "nhl"))).all()
    assert games, "NHL API returned no games for the week of 2026-01-12"
    assert any(g.status == "final" and g.home_score is not None for g in games)
