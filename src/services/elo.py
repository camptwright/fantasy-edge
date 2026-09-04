"""A transparent Elo rating model - the "honest baseline," not the deferred
full market-anchored/market-independent joint-distribution model.

Standard Elo update, run once per game the moment its score is finalized
(see the was_final/is_final transition guard in src/ingest/espn.py's
_upsert_event - this must never re-apply on a later poll of an
already-final game). Constants below are commonly-cited approximations for
American football, not tuned or calibrated against this application's own
data - that calibration work is real future work, not something to fake
with borrowed precision.

Deliberately stdlib-only (math.erf for the normal CDF, not scipy.stats):
this runs inside sync_espn(), which is part of the serving path, and the
architecture's own principle is that the serving image carries no offline
modeling dependencies (see docs/superpowers/specs/2026-08-20-fantasy-edge-nfl-rebuild-design.md).

update_ratings_after_game also maintains each team's running points-
scored/allowed average on the same TeamRating row, at the same moment
(idempotency and the was_final transition guard both already apply here
unchanged) - see src/services/totals.py, which reads those averages for
the totals-market baseline the Elo rating itself cannot provide.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.facts import Game
from src.models.ratings import STARTING_RATING, TeamRating
from src.utils.odds_math import normal_cdf

K_FACTOR = 20.0
HOME_FIELD_ADVANTAGE = 65.0  # rating points added to the home side pre-game

# Rough Elo-points-per-point-of-margin scaling, in the style of
# fivethirtyeight's NFL Elo system. Applied to both sports as a documented
# approximation, not a fitted value.
RATING_POINTS_PER_MARGIN_POINT = 25.0

# Approximate standard deviation of final score margin. NCAAF's much wider
# range of team quality and higher-possession games produce more spread in
# final margins than the NFL's tighter competitive balance.
MARGIN_STDDEV = {"nfl": 13.5, "ncaaf": 17.0}


async def _get_or_create_rating(db: AsyncSession, team_id: uuid.UUID, sport: str) -> TeamRating:
    rating = await db.scalar(select(TeamRating).where(TeamRating.team_id == team_id))
    if rating is not None:
        return rating
    rating = TeamRating(team_id=team_id, sport=sport, rating=STARTING_RATING)
    db.add(rating)
    await db.flush()
    return rating


def expected_score(rating_a: float, rating_b: float) -> float:
    """Standard Elo expected-score (win probability) for side A."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


async def update_ratings_after_game(db: AsyncSession, game: Game) -> None:
    """Apply one Elo update for a just-finalized game. Idempotency (never
    double-applying to an already-final game) is the caller's
    responsibility - see the was_final transition guard in espn.py."""
    if game.home_team_id is None or game.away_team_id is None:
        return
    if game.home_score is None or game.away_score is None:
        return

    home = await _get_or_create_rating(db, game.home_team_id, game.sport)
    away = await _get_or_create_rating(db, game.away_team_id, game.sport)

    if game.home_score > game.away_score:
        actual_home = 1.0
    elif game.home_score < game.away_score:
        actual_home = 0.0
    else:
        actual_home = 0.5

    expected_home = expected_score(home.rating + HOME_FIELD_ADVANTAGE, away.rating)
    delta = K_FACTOR * (actual_home - expected_home)
    home.rating += delta
    away.rating -= delta

    _update_scoring_average(home, scored=game.home_score, allowed=game.away_score)
    _update_scoring_average(away, scored=game.away_score, allowed=game.home_score)

    await db.flush()


def _update_scoring_average(rating: TeamRating, *, scored: int, allowed: int) -> None:
    """Incremental (running) mean - avoids re-scanning every prior game's
    score just to add one more, the same reason src/ingest/lines.py favours
    an insert-on-change comparison over a full re-aggregation."""
    n = rating.games_played
    prior_scored = rating.avg_points_scored if rating.avg_points_scored is not None else float(scored)
    prior_allowed = rating.avg_points_allowed if rating.avg_points_allowed is not None else float(allowed)
    rating.avg_points_scored = prior_scored + (scored - prior_scored) / (n + 1)
    rating.avg_points_allowed = prior_allowed + (allowed - prior_allowed) / (n + 1)
    rating.games_played = n + 1


def moneyline_probability(rating_home: float, rating_away: float) -> float:
    """Home win probability, including home-field advantage."""
    return expected_score(rating_home + HOME_FIELD_ADVANTAGE, rating_away)


def implied_margin(rating_home: float, rating_away: float) -> float:
    """Expected home-minus-away point margin implied by the rating gap."""
    return (rating_home + HOME_FIELD_ADVANTAGE - rating_away) / RATING_POINTS_PER_MARGIN_POINT


def spread_cover_probability(rating_home: float, rating_away: float, home_line: float, sport: str) -> float:
    """P(home team covers `home_line`), home_line in the sportsbook
    convention (negative = home favoured, see src/models/facts.py).

    Home covers when actual_margin > -home_line. Margin is modeled as
    Normal(implied_margin, MARGIN_STDDEV[sport]) - the empirical
    non-normal clustering at 3/7 the original design doc calls out is a
    refinement for a real fitted model, not this baseline.
    """
    margin = implied_margin(rating_home, rating_away)
    sigma = MARGIN_STDDEV.get(sport, MARGIN_STDDEV["nfl"])
    return 1.0 - normal_cdf((-home_line - margin) / sigma)
