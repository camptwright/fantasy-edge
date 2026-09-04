"""NCAAF player-game stats from ESPN's boxscore (src/ingest/
ncaaf_player_stats.py): offline unit tests against a fake payload shaped
like the real endpoint, plus one live smoke test.

Real shape verified live 2026-09-05 against a real finished 2025 game's
/summary endpoint - passing carries a compound "completions/
passingAttempts" field; rushing/receiving do not.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.ingest.identity import resolve_player, resolve_team
from src.ingest.ncaaf_player_stats import _ingest_category, ingest_player_stats
from src.ingest.ncaaf_players import _upsert_player
from src.ingest.ncaaf_players import ingest_players as seed_ncaaf_players
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player


def _passing_category(athlete_id: str = "5296439", full_name: str = "Deuce Bailey") -> dict:
    return {
        "name": "passing",
        "keys": ["completions/passingAttempts", "passingYards", "yardsPerPassAttempt", "passingTouchdowns", "interceptions", "adjQBR"],
        "athletes": [
            {"athlete": {"id": athlete_id, "displayName": full_name}, "stats": ["16/31", "278", "9.0", "1", "0", "17.1"]}
        ],
    }


def _receiving_category(athlete_id: str = "9999", full_name: str = "Ramone Green Jr.") -> dict:
    return {
        "name": "receiving",
        "keys": ["receptions", "receivingYards", "yardsPerReception", "receivingTouchdowns", "longReception"],
        "athletes": [
            {"athlete": {"id": athlete_id, "displayName": full_name}, "stats": ["1", "76", "76.0", "0", "76"]}
        ],
    }


async def _seed_ncaaf_game(db) -> Game:
    home_team = await resolve_team(db, "Ohio State Buckeyes", sport="ncaaf")
    away_team = await resolve_team(db, "Michigan Wolverines", sport="ncaaf")
    game = Game(
        sport="ncaaf", espn_event_id="ncaaf-stat-test-1", season=2025,
        home_team_id=home_team.id, away_team_id=away_team.id, status="final",
    )
    db.add(game)
    await db.flush()
    return game


async def test_ingest_category_writes_split_compound_and_mapped_stats(db):
    await _upsert_player(db, {"id": "5296439", "fullName": "Deuce Bailey"})
    await db.commit()
    game = await _seed_ncaaf_game(db)

    written = await _ingest_category(db, game.id, _passing_category())
    await db.commit()

    # completions, passingAttempts (split from the compound field),
    # passingYards, passingTouchdowns, interceptions -> 5 rows. QBR and
    # yardsPerPassAttempt are deliberately not in the curated stat map.
    assert written == 5

    player = await resolve_player(db, source="espn_ncaaf", external_id="5296439", full_name="Deuce Bailey", sport="ncaaf")
    rows = {
        row.stat_type: row.value
        for row in (await db.execute(select(PlayerGameStat).where(PlayerGameStat.player_id == player.id))).scalars()
    }
    assert rows == {
        "passing_completions": 16.0,
        "passing_attempts": 31.0,
        "passing_yards": 278.0,
        "passing_touchdowns": 1.0,
        "ints_thrown": 0.0,
    }


async def test_ingest_category_writes_receiving_stats_with_canonical_names_matching_real_props(db):
    await _upsert_player(db, {"id": "9999", "fullName": "Ramone Green Jr."})
    await db.commit()
    game = await _seed_ncaaf_game(db)

    written = await _ingest_category(db, game.id, _receiving_category())
    await db.commit()

    assert written == 4  # receptions, receivingYards, receivingTouchdowns, longReception
    player = await resolve_player(db, source="espn_ncaaf", external_id="9999", full_name="Ramone Green Jr.", sport="ncaaf")
    rows = {
        row.stat_type: row.value
        for row in (await db.execute(select(PlayerGameStat).where(PlayerGameStat.player_id == player.id))).scalars()
    }
    # Canonical names must match what real NCAAF props already use verbatim
    # (checked live against this app's own player_prop_lines) - this is
    # the whole point of the ingestion, not an incidental detail.
    assert rows["receptions"] == 1.0
    assert rows["receiving_yards"] == 76.0
    assert rows["longest_reception"] == 76.0


async def test_unresolvable_athlete_is_skipped_not_raised(db):
    game = await _seed_ncaaf_game(db)
    written = await _ingest_category(db, game.id, _passing_category(athlete_id="404040"))
    assert written == 0

    count = await db.scalar(select(PlayerGameStat.id).limit(1))
    assert count is None


async def test_ingest_player_stats_is_a_noop_with_no_final_games(db):
    written = await ingest_player_stats(db, seasons=[2025])
    assert written == 0


@pytest.mark.live
async def test_live_ingest_seeds_real_stats_for_a_finished_game(db):
    home = await resolve_team(db, "Missouri State Bears", sport="ncaaf")
    away = await resolve_team(db, "Middle Tennessee Blue Raiders", sport="ncaaf")
    game = Game(
        sport="ncaaf", espn_event_id="401757278", season=2025,
        home_team_id=home.id, away_team_id=away.id, status="final",
    )
    db.add(game)
    await db.commit()

    await seed_ncaaf_players(db)

    written = await ingest_player_stats(db, seasons=[2025])
    assert written > 0, "ESPN returned no boxscore stats for a real finished game"

    players_with_stats = await db.scalar(
        select(Player.id).join(PlayerGameStat, PlayerGameStat.player_id == Player.id).limit(1)
    )
    assert players_with_stats is not None
