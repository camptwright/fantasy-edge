"""Walk-forward calibration backtest - the honest way to answer "is the
Elo/totals baseline actually well-calibrated": replay every finished game
in chronological order using ONLY information available before that game,
never today's rating. This is exactly the discipline
src/api/routers/sportsbook.py's signal_rows learned it was missing the
hard way (a completed game got priced with a rating that already included
that game's own outcome, producing a real 235% "EV" - see that function's
own docstring). A calibration check that reused the live team_ratings
table would repeat precisely that mistake at the model-evaluation level
instead of the display level.

Ratings are walked forward in a plain in-memory TeamState dict, never the
live table - a backtest must not disturb production state, and replaying
from a fresh 1500 baseline is the only way to recover each game's true
pre-game rating. apply_result/update_scoring_average (src/services/elo.py)
are the same pure functions production uses, so this evaluates exactly
the model that's actually running, not a reimplementation of it.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.facts import Game, TeamMarketLine
from src.models.ratings import STARTING_RATING
from src.services.elo import apply_result, moneyline_probability, spread_cover_probability, update_scoring_average
from src.services.totals import expected_total_points, is_qualified, total_over_probability


@dataclass
class TeamState:
    """Duck-types as a TeamRating for update_scoring_average/is_qualified -
    see elo.py's own docstring on why that's intentional, not incidental."""

    rating: float = STARTING_RATING
    avg_points_scored: float | None = None
    avg_points_allowed: float | None = None
    games_played: int = 0


@dataclass
class BacktestPrediction:
    game_id: uuid.UUID
    market: str  # moneyline | spread | total
    probability: float
    outcome: float  # 1.0 or 0.0 - pushes are excluded before this is built


async def _closing_lines_by_game(db: AsyncSession, game_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, float]]:
    """The home side's own spread/total number per game, from whichever
    line was recorded first (append-only observation history - the
    opening/earliest number is the closest thing to "the market's honest
    pre-game view" this schema has short of a dedicated closing-line
    column). Only used to know WHAT number the market posted, never to
    decide who is favored - that stays the model's own job."""
    if not game_ids:
        return {}
    rows = (
        await db.execute(
            select(TeamMarketLine)
            .where(
                TeamMarketLine.game_id.in_(game_ids),
                TeamMarketLine.market.in_(("spread", "total")),
                TeamMarketLine.side.in_(("home", "over")),
            )
            .order_by(TeamMarketLine.observed_at.asc())
        )
    ).scalars()

    result: dict[uuid.UUID, dict[str, float]] = {}
    for line in rows:
        if line.line is None:
            continue
        bucket = result.setdefault(line.game_id, {})
        key = "spread" if line.market == "spread" else "total"
        bucket.setdefault(key, line.line)
    return result


async def run_backtest(db: AsyncSession, sport: str, seasons: list[int]) -> list[BacktestPrediction]:
    games = (
        await db.execute(
            select(Game)
            .where(
                Game.sport == sport,
                Game.season.in_(seasons),
                Game.status == "final",
                Game.home_score.isnot(None),
                Game.away_score.isnot(None),
            )
            .order_by(Game.game_time.asc().nulls_last())
        )
    ).scalars().all()

    lines = await _closing_lines_by_game(db, [g.id for g in games])
    states: dict[uuid.UUID, TeamState] = {}
    predictions: list[BacktestPrediction] = []

    for game in games:
        if game.home_team_id is None or game.away_team_id is None:
            continue
        home = states.setdefault(game.home_team_id, TeamState())
        away = states.setdefault(game.away_team_id, TeamState())
        margin = game.home_score - game.away_score

        if margin != 0:
            home_won = 1.0 if margin > 0 else 0.0
            predictions.append(
                BacktestPrediction(
                    game.id, "moneyline", moneyline_probability(home.rating, away.rating), home_won
                )
            )

        game_lines = lines.get(game.id, {})
        spread_line = game_lines.get("spread")
        if spread_line is not None and margin != -spread_line:
            covered = 1.0 if margin > -spread_line else 0.0
            prob = spread_cover_probability(home.rating, away.rating, spread_line, sport)
            predictions.append(BacktestPrediction(game.id, "spread", prob, covered))

        total_line = game_lines.get("total")
        actual_total = game.home_score + game.away_score
        if total_line is not None and actual_total != total_line and is_qualified(home) and is_qualified(away):
            over = 1.0 if actual_total > total_line else 0.0
            expected_total = expected_total_points(home, away)
            prob = total_over_probability(expected_total, total_line, sport)
            predictions.append(BacktestPrediction(game.id, "total", prob, over))

        # Apply THIS game's own update only after every prediction above
        # already used the pre-game state - the entire point of walking
        # forward instead of reading today's rating.
        home.rating, away.rating = apply_result(home.rating, away.rating, game.home_score, game.away_score)
        update_scoring_average(home, scored=game.home_score, allowed=game.away_score)
        update_scoring_average(away, scored=game.away_score, allowed=game.home_score)

    return predictions


def brier_score(predictions: list[BacktestPrediction]) -> float | None:
    """Mean squared error between predicted probability and the realized
    0/1 outcome. 0 is perfect; 0.25 is what predicting a flat 50% on every
    game scores - the "beats a coin flip" reference point
    CalibrationReport's passed_gate uses."""
    if not predictions:
        return None
    return sum((p.probability - p.outcome) ** 2 for p in predictions) / len(predictions)


def log_loss(predictions: list[BacktestPrediction]) -> float | None:
    if not predictions:
        return None
    eps = 1e-9
    total = 0.0
    for p in predictions:
        prob = min(max(p.probability, eps), 1.0 - eps)
        total += -(p.outcome * math.log(prob) + (1.0 - p.outcome) * math.log(1.0 - prob))
    return total / len(predictions)


def calibration_curve(predictions: list[BacktestPrediction], bins: int = 5) -> list[dict[str, float]]:
    """Bucket predictions by predicted probability and compare each
    bucket's average prediction to its average realized outcome - the
    single most interpretable calibration readout: "when the model said
    60-80% win probability, the home team actually won X% of the time."
    """
    buckets: list[list[BacktestPrediction]] = [[] for _ in range(bins)]
    for p in predictions:
        index = min(int(p.probability * bins), bins - 1)
        buckets[index].append(p)

    curve = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        curve.append(
            {
                "range_low": i / bins,
                "range_high": (i + 1) / bins,
                "count": len(bucket),
                "avg_predicted": sum(p.probability for p in bucket) / len(bucket),
                "avg_actual": sum(p.outcome for p in bucket) / len(bucket),
            }
        )
    return curve
