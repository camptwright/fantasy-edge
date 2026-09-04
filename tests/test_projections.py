"""Baseline player-prop projections (src/services/projections.py)."""

from __future__ import annotations

import pytest

from src.ingest.identity import resolve_team
from src.models.facts import PlayerGameStat
from src.models.identity import Player
from src.services.projections import MIN_GAMES_FOR_PROJECTION, over_probability, project_stats


async def _seed_player_with_games(db, values: list[float], stat_type: str = "passing_yards") -> Player:
    team = await resolve_team(db, "Kansas City Chiefs")
    player = Player(sport="nfl", full_name="Projection Test Player", current_team_id=team.id)
    db.add(player)
    await db.flush()
    for i, value in enumerate(values):
        db.add(
            # game_id nullable-in-practice-here would break the NOT NULL FK,
            # so a distinct dummy game per row keeps uq_player_game_stat
            # (player_id, game_id, stat_type) satisfied - only the value
            # distribution matters for this service, not which game it
            # came from.
            PlayerGameStat(player_id=player.id, game_id=await _dummy_game_id(db, i), stat_type=stat_type, value=value)
        )
    await db.flush()
    return player


async def _dummy_game_id(db, salt: int):
    from src.models.facts import Game

    team = await resolve_team(db, "Kansas City Chiefs")
    opp = await resolve_team(db, "Los Angeles Chargers")
    game = Game(
        sport="nfl", espn_event_id=f"proj-test-{salt}", season=2026,
        home_team_id=team.id, away_team_id=opp.id, status="final",
    )
    db.add(game)
    await db.flush()
    return game.id


async def test_fewer_than_minimum_games_does_not_qualify(db):
    player = await _seed_player_with_games(db, [250.0, 275.0, 300.0])  # 3, one short
    assert MIN_GAMES_FOR_PROJECTION == 4

    result = await project_stats(db, {(player.id, "passing_yards")})
    assert result == {}


async def test_minimum_games_qualifies_and_returns_mean_and_stddev(db):
    values = [250.0, 275.0, 300.0, 225.0]
    player = await _seed_player_with_games(db, values)

    result = await project_stats(db, {(player.id, "passing_yards")})
    mean, stddev = result[(player.id, "passing_yards")]
    assert mean == pytest.approx(sum(values) / len(values))
    assert stddev > 0


async def test_zero_variance_history_does_not_qualify(db):
    """Every game identical would make over_probability degenerate to
    exactly 0 or 1 - false certainty, not a real signal - so this is
    treated the same as not-yet-qualified."""
    player = await _seed_player_with_games(db, [70.0, 70.0, 70.0, 70.0], stat_type="rushing_yards")
    result = await project_stats(db, {(player.id, "rushing_yards")})
    assert result == {}


async def test_unrequested_stat_types_for_the_same_player_are_not_returned(db):
    """A player can have other stat_types with plenty of history - only
    the keys actually requested must come back, not everything the bulk
    query happened to fetch for that player_id."""
    player = await _seed_player_with_games(db, [250.0, 275.0, 300.0, 225.0], stat_type="passing_yards")

    result = await project_stats(db, {(player.id, "rushing_yards")})
    assert result == {}


def test_over_probability_is_fifty_fifty_at_the_mean():
    assert over_probability(mean=250.0, stddev=40.0, line=250.0) == pytest.approx(0.5, abs=1e-6)


def test_over_probability_favors_the_over_when_the_line_is_well_below_the_mean():
    assert over_probability(mean=250.0, stddev=40.0, line=150.0) > 0.9


def test_over_probability_favors_the_under_when_the_line_is_well_above_the_mean():
    assert over_probability(mean=250.0, stddev=40.0, line=320.0) < 0.1
