"""The totals-market baseline (src/services/totals.py) - pure math, no
database needed. TeamRating is constructed directly rather than persisted;
these functions only read its scoring-average fields."""

from __future__ import annotations

import pytest

from src.models.ratings import TeamRating
from src.services.totals import (
    MIN_GAMES_FOR_TOTALS,
    expected_total_points,
    is_qualified,
    total_over_probability,
)


def _rating(*, scored: float | None, allowed: float | None, games: int) -> TeamRating:
    return TeamRating(
        team_id=None, sport="nfl", rating=1500.0,
        avg_points_scored=scored, avg_points_allowed=allowed, games_played=games,
    )


def test_qualified_requires_the_minimum_games_played():
    below = _rating(scored=24.0, allowed=20.0, games=MIN_GAMES_FOR_TOTALS - 1)
    at = _rating(scored=24.0, allowed=20.0, games=MIN_GAMES_FOR_TOTALS)
    assert is_qualified(below) is False
    assert is_qualified(at) is True


def test_qualified_requires_averages_to_actually_exist():
    fresh = _rating(scored=None, allowed=None, games=0)
    assert is_qualified(fresh) is False


def test_expected_total_averages_each_side_own_offense_against_the_others_defense():
    # Home scores 30/allows 20 on average; away scores 24/allows 27.
    home = _rating(scored=30.0, allowed=20.0, games=5)
    away = _rating(scored=24.0, allowed=27.0, games=5)

    expected_home_points = (30.0 + 27.0) / 2.0  # home offense vs away defense
    expected_away_points = (24.0 + 20.0) / 2.0  # away offense vs home defense
    assert expected_total_points(home, away) == pytest.approx(
        expected_home_points + expected_away_points
    )


def test_symmetric_teams_produce_a_fifty_fifty_total_line():
    home = _rating(scored=24.0, allowed=24.0, games=5)
    away = _rating(scored=24.0, allowed=24.0, games=5)
    expected = expected_total_points(home, away)  # 48.0

    assert total_over_probability(expected, expected, "nfl") == pytest.approx(0.5, abs=1e-6)


def test_a_much_lower_posted_total_strongly_favors_the_over():
    home = _rating(scored=30.0, allowed=24.0, games=5)
    away = _rating(scored=28.0, allowed=22.0, games=5)
    expected = expected_total_points(home, away)

    assert total_over_probability(expected, expected - 15.0, "nfl") > 0.9


def test_ncaaf_uses_wider_sigma_than_nfl_for_the_identical_gap():
    home = _rating(scored=30.0, allowed=20.0, games=5)
    away = _rating(scored=24.0, allowed=27.0, games=5)
    expected = expected_total_points(home, away)
    posted = expected - 5.0

    nfl_prob = total_over_probability(expected, posted, "nfl")
    ncaaf_prob = total_over_probability(expected, posted, "ncaaf")
    assert abs(ncaaf_prob - 0.5) < abs(nfl_prob - 0.5)
