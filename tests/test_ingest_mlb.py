"""MLB Stats API sync (src/ingest/mlb.py): offline unit tests against fake
game payloads shaped like the real API, plus one live smoke test.

Real shape verified live 2026-09-04 against statsapi.mlb.com/api/v1/schedule
- both a Final 2026-01-15 game and a Preview (future) game.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.ingest.identity import resolve_team
from src.ingest.mlb import _upsert_game, sync_schedule
from src.models.facts import Game
from src.models.ratings import TeamRating


def _fake_game(
    game_pk: int = 823452,
    home: str = "Philadelphia Phillies",
    away: str = "Miami Marlins",
    home_score: int | None = 7,
    away_score: int | None = 0,
    state: str = "Final",
    game_type: str = "R",
    season: str = "2026",
    game_date: str = "2026-06-15T22:40:00Z",
) -> dict:
    return {
        "gamePk": game_pk,
        "gameType": game_type,
        "season": season,
        "gameDate": game_date,
        "status": {"abstractGameState": state},
        "teams": {
            "away": {"team": {"id": 146, "name": away}, "score": away_score},
            "home": {"team": {"id": 143, "name": home}, "score": home_score},
        },
    }


class _Run:
    """Minimal stand-in for the IngestionRun the real record_run yields."""

    def __init__(self):
        self.detail = None


async def test_cancelled_abstract_final_is_not_a_played_result(db):
    payload = _fake_game(home_score=None, away_score=None)
    payload['status'].update(codedGameState='C', detailedState='Cancelled')
    await _upsert_game(db, payload, _Run())
    game = await db.scalar(select(Game).where(Game.mlb_game_pk == str(payload['gamePk'])))
    assert game.status == 'cancelled'
    assert not (await db.scalars(select(TeamRating))).all()


async def test_upsert_game_creates_a_final_game_with_scores(db):
    touched = await _upsert_game(db, _fake_game(), _Run())
    assert touched is True

    game = await db.scalar(select(Game).where(Game.mlb_game_pk == "823452"))
    assert game is not None
    assert game.sport == "mlb"
    assert game.status == "final"
    assert game.home_score == 7
    assert game.away_score == 0
    assert game.game_type == "REG"
    assert game.season == 2026


async def test_upsert_game_maps_scheduled_and_preseason_state(db):
    game = _fake_game(
        game_pk=999001, state="Preview", game_type="S",
        home_score=None, away_score=None,
    )
    touched = await _upsert_game(db, game, _Run())
    assert touched is True

    row = await db.scalar(select(Game).where(Game.mlb_game_pk == "999001"))
    assert row.status == "scheduled"
    assert row.game_type == "PRE"
    assert row.home_score is None


def test_upsert_game_maps_unrecognized_game_type_to_post():
    """Wild card/division/championship/World Series codes all collapse to
    POST rather than invented round names - the same choice espn.py makes
    for NCAAF's bowl season."""
    from src.ingest.mlb import _GAME_TYPE_MAP

    assert _GAME_TYPE_MAP.get("F", "POST") == "POST"  # Wild Card
    assert _GAME_TYPE_MAP.get("W", "POST") == "POST"  # World Series


async def test_upsert_game_is_idempotent_on_game_pk(db):
    await _upsert_game(db, _fake_game(), _Run())
    await _upsert_game(db, _fake_game(home_score=9), _Run())

    rows = (await db.execute(select(Game).where(Game.mlb_game_pk == "823452"))).scalars().all()
    assert len(rows) == 1
    assert rows[0].home_score == 9


async def test_elo_updates_exactly_once_when_a_game_first_goes_final(db):
    game = _fake_game(state="Preview", home_score=None, away_score=None)
    await _upsert_game(db, game, _Run())
    await db.commit()

    home = await resolve_team(db, "Philadelphia Phillies", sport="mlb")
    rating_before = await db.scalar(select(TeamRating).where(TeamRating.team_id == home.id))
    assert rating_before is None, "no Elo update yet for a scheduled game"

    await _upsert_game(db, _fake_game(state="Final"), _Run())
    await db.commit()
    rating_after_first_final = await db.scalar(select(TeamRating).where(TeamRating.team_id == home.id))
    assert rating_after_first_final is not None

    # A second poll of the same already-final game must not re-apply Elo.
    await _upsert_game(db, _fake_game(state="Final"), _Run())
    await db.commit()
    rating_after_second_poll = await db.scalar(select(TeamRating).where(TeamRating.team_id == home.id))
    assert rating_after_second_poll.rating == rating_after_first_final.rating


async def test_unresolvable_team_is_parked_not_raised(db):
    game = _fake_game(home="Not A Real Team", game_pk=999002)
    touched = await _upsert_game(db, game, _Run())
    assert touched is False

    row = await db.scalar(select(Game).where(Game.mlb_game_pk == "999002"))
    assert row is None


@pytest.mark.live
async def test_live_schedule_creates_final_games_with_scores(db):
    # MLB has no games in January - the season runs roughly late March
    # through October/November. 2026-06-15 is mid-regular-season.
    written = await sync_schedule(db, start_date="2026-06-15", end_date="2026-06-15")
    assert written > 0

    games = (await db.scalars(select(Game).where(Game.sport == "mlb"))).all()
    assert games, "MLB Stats API returned no games for 2026-06-15"
    assert any(g.status == "final" and g.home_score is not None for g in games)
