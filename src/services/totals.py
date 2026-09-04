"""Totals-market baseline - each team's own scoring level, not the Elo
rating.

Elo (src/services/elo.py) encodes relative team strength (who wins, by how
much) from win/loss outcomes; it says nothing about how many points either
team tends to score or allow, so it cannot honestly price a total. This
model instead uses each team's running average points scored/allowed
(TeamRating.avg_points_scored/avg_points_allowed, maintained by
elo.py's update_ratings_after_game at the same moment as the rating
update) - a standard "own offense vs. opponent's own defense" total,
deliberately as simple and transparent as the Elo baseline itself, not a
fitted model.
"""

from __future__ import annotations

from src.models.ratings import TeamRating
from src.utils.odds_math import normal_cdf

# A team's average is not trustworthy on a handful of games - matches the
# same "omit rather than assume" discipline as the Elo baseline (see
# src/api/routers/sportsbook.py's own "no Elo history for one side yet"
# comment).
MIN_GAMES_FOR_TOTALS = 3

# Approximate standard deviation of total (combined) points, in the same
# commonly-cited-approximation spirit as elo.py's MARGIN_STDDEV - not
# fitted or calibrated against this application's own data.
TOTAL_STDDEV = {"nfl": 10.5, "ncaaf": 14.0}


def is_qualified(rating: TeamRating) -> bool:
    return (
        rating.games_played >= MIN_GAMES_FOR_TOTALS
        and rating.avg_points_scored is not None
        and rating.avg_points_allowed is not None
    )


def expected_total_points(home: TeamRating, away: TeamRating) -> float:
    """Each side's expected points is the average of its own scoring
    average and the opponent's own allowed average; the total is their
    sum."""
    expected_home = (home.avg_points_scored + away.avg_points_allowed) / 2.0
    expected_away = (away.avg_points_scored + home.avg_points_allowed) / 2.0
    return expected_home + expected_away


def total_over_probability(expected_total: float, posted_total: float, sport: str) -> float:
    """P(actual combined score > posted_total), modelling the total as
    Normal(expected_total, TOTAL_STDDEV[sport])."""
    sigma = TOTAL_STDDEV.get(sport, TOTAL_STDDEV["nfl"])
    return 1.0 - normal_cdf((posted_total - expected_total) / sigma)
