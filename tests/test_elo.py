"""The transparent Elo baseline (src/services/elo.py).

Pure-math tests need no database; update_ratings_after_game does, since it
persists TeamRating rows.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.ingest.identity import resolve_team
from src.models.facts import Game
from src.models.ratings import STARTING_RATING, TeamRating
from src.services.elo import (
    expected_score,
    implied_margin,
    moneyline_probability,
    spread_cover_probability,
    update_ratings_after_game,
)


def test_expected_score_is_symmetric_for_equal_ratings():
    assert expected_score(1500, 1500) == pytest.approx(0.5)


def test_expected_score_favors_the_higher_rating():
    assert expected_score(1600, 1400) > 0.5
    assert expected_score(1400, 1600) < 0.5


def test_moneyline_probability_includes_home_field_advantage():
    """Equal ratings must still favor the home side - that's the entire
    point of a home-field constant existing."""
    assert moneyline_probability(1500, 1500) > 0.5


def test_implied_margin_is_zero_for_equal_ratings_minus_home_field():
    """Equal ratings imply a small home-favored margin, not exactly zero -
    home field advantage is baked into the same conversion used for win
    probability, not a separate untested path."""
    assert implied_margin(1500, 1500) > 0


def test_spread_cover_probability_favors_a_big_home_favorite():
    # Home team rated far higher, laying a modest spread: should be a
    # heavily favored cover, not a coin flip.
    prob = spread_cover_probability(1700, 1300, home_line=-3.0, sport="nfl")
    assert prob > 0.7


def test_spread_cover_probability_ncaaf_uses_wider_sigma_than_nfl():
    """NCAAF's higher score variance (MARGIN_STDDEV) must produce a less
    extreme probability than NFL for the identical rating gap and line -
    otherwise the per-sport sigma isn't actually being used."""
    nfl_prob = spread_cover_probability(1700, 1300, home_line=-3.0, sport="nfl")
    ncaaf_prob = spread_cover_probability(1700, 1300, home_line=-3.0, sport="ncaaf")
    assert abs(ncaaf_prob - 0.5) < abs(nfl_prob - 0.5)


async def test_update_ratings_moves_winner_up_and_loser_down(db):
    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Los Angeles Chargers")
    game = Game(
        sport="nfl",
        espn_event_id="elo-test-1",
        season=2026,
        home_team_id=home.id,
        away_team_id=away.id,
        home_score=30,
        away_score=10,
        status="final",
    )
    db.add(game)
    await db.flush()

    await update_ratings_after_game(db, game)
    await db.commit()

    home_rating = await db.scalar(select(TeamRating).where(TeamRating.team_id == home.id))
    away_rating = await db.scalar(select(TeamRating).where(TeamRating.team_id == away.id))

    assert home_rating.rating > STARTING_RATING, "the decisive winner's rating must rise"
    assert away_rating.rating < STARTING_RATING, "the decisive loser's rating must fall"
    # Zero-sum: the winner's gain must exactly equal the loser's loss.
    assert (home_rating.rating - STARTING_RATING) == pytest.approx(
        -(away_rating.rating - STARTING_RATING)
    )


async def test_update_ratings_also_maintains_scoring_averages(db):
    """The totals baseline (src/services/totals.py) reads
    avg_points_scored/avg_points_allowed/games_played off the same
    TeamRating row the Elo update already writes - this proves that side
    of the update actually runs, not just the rating."""
    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Los Angeles Chargers")
    game = Game(
        sport="nfl", espn_event_id="elo-test-3", season=2026,
        home_team_id=home.id, away_team_id=away.id,
        home_score=30, away_score=10, status="final",
    )
    db.add(game)
    await db.flush()

    await update_ratings_after_game(db, game)
    await db.commit()

    home_rating = await db.scalar(select(TeamRating).where(TeamRating.team_id == home.id))
    away_rating = await db.scalar(select(TeamRating).where(TeamRating.team_id == away.id))

    assert home_rating.avg_points_scored == pytest.approx(30.0)
    assert home_rating.avg_points_allowed == pytest.approx(10.0)
    assert away_rating.avg_points_scored == pytest.approx(10.0)
    assert away_rating.avg_points_allowed == pytest.approx(30.0)
    assert home_rating.games_played == 1
    assert away_rating.games_played == 1


async def test_scoring_average_is_a_running_mean_across_games(db):
    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Los Angeles Chargers")
    third = await resolve_team(db, "Denver Broncos")

    game_one = Game(
        sport="nfl", espn_event_id="elo-test-4a", season=2026,
        home_team_id=home.id, away_team_id=away.id,
        home_score=30, away_score=10, status="final",
    )
    db.add(game_one)
    await db.flush()
    await update_ratings_after_game(db, game_one)
    await db.commit()

    game_two = Game(
        sport="nfl", espn_event_id="elo-test-4b", season=2026,
        home_team_id=home.id, away_team_id=third.id,
        home_score=20, away_score=17, status="final",
    )
    db.add(game_two)
    await db.flush()
    await update_ratings_after_game(db, game_two)
    await db.commit()

    home_rating = await db.scalar(select(TeamRating).where(TeamRating.team_id == home.id))
    assert home_rating.games_played == 2
    assert home_rating.avg_points_scored == pytest.approx((30 + 20) / 2)
    assert home_rating.avg_points_allowed == pytest.approx((10 + 17) / 2)


async def test_update_ratings_is_a_noop_without_both_scores(db):
    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Los Angeles Chargers")
    game = Game(
        sport="nfl",
        espn_event_id="elo-test-2",
        season=2026,
        home_team_id=home.id,
        away_team_id=away.id,
        status="scheduled",
    )
    db.add(game)
    await db.flush()

    await update_ratings_after_game(db, game)
    await db.commit()

    rating = await db.scalar(select(TeamRating))
    assert rating is None, "an unfinished game must not create any rating rows"
