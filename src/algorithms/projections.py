"""Player fantasy-point projections from rolling form, opponent strength,
and usage trends.

Deliberately NOT a trained model - unlike the game-outcome ensemble, a
single-player projection has to work reasonably well from day one with
whatever handful of recent games exist, including a rookie's first career
game (zero history). A weighted-rolling-average approach degrades gracefully
in that case (falls back to season/position averages) where a trained
regressor would need retraining before it could say anything useful at all.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GameStatLine:
    """One player's fantasy output in one past game, oldest-first order not
    required - `project` sorts internally by `games_ago`."""

    games_ago: int  # 1 = most recent game, 2 = two games ago, etc.
    fantasy_points: float
    minutes: float | None = None
    opponent_defensive_rank: int | None = None  # 1 = toughest defense


@dataclass
class ProjectionResult:
    projected_points: float
    floor: float
    ceiling: float
    trend: str  # rising | falling | stable
    games_used: int
    confidence: str  # low | medium | high


# Exponential-ish decay by recency: last game matters most, but a full
# season of role stability should outweigh one hot/cold night. Weights for
# games beyond index 4 all use the last (smallest) value.
_RECENCY_WEIGHTS = [0.30, 0.22, 0.17, 0.13, 0.10, 0.08]


def _recency_weight(games_ago: int) -> float:
    idx = min(games_ago - 1, len(_RECENCY_WEIGHTS) - 1)
    return _RECENCY_WEIGHTS[idx]


def _weighted_mean(values: list[tuple[float, float]]) -> float:
    """`values` is [(value, weight), ...]."""
    total_weight = sum(w for _, w in values)
    if total_weight == 0:
        return 0.0
    return sum(v * w for v, w in values) / total_weight


def project(
    recent_games: list[GameStatLine],
    *,
    season_average: float | None = None,
    position_average: float | None = None,
    opponent_defensive_rank: int | None = None,
    league_avg_defensive_rank: float = 15.5,
) -> ProjectionResult:
    """`season_average`/`position_average` are the graceful-degradation
    fallbacks for low-sample players (early season, recent call-up, role
    change) - a rookie's first game has no `recent_games` at all, and the
    result should still be a sane number, not zero or an exception.
    """
    if not recent_games:
        base = season_average if season_average is not None else position_average
        if base is None:
            return ProjectionResult(
                projected_points=0.0,
                floor=0.0,
                ceiling=0.0,
                trend="stable",
                games_used=0,
                confidence="low",
            )
        return ProjectionResult(
            projected_points=base,
            floor=base * 0.6,
            ceiling=base * 1.4,
            trend="stable",
            games_used=0,
            confidence="low",
        )

    sorted_games = sorted(recent_games, key=lambda g: g.games_ago)
    weighted_values = [(g.fantasy_points, _recency_weight(g.games_ago)) for g in sorted_games]
    rolling_projection = _weighted_mean(weighted_values)

    # Blend toward the season average when the sample is thin, so three
    # huge games early in a season don't get taken at 100% face value.
    n = len(sorted_games)
    if season_average is not None and n < 5:
        blend_weight = n / 5.0
        rolling_projection = (
            rolling_projection * blend_weight + season_average * (1 - blend_weight)
        )

    # Opponent adjustment: playing a bottom-5 defense nudges the projection
    # up, a top-5 defense nudges it down. Capped at +/-15% so one matchup
    # factor never dominates a player's established form.
    if opponent_defensive_rank is not None:
        rank_delta = opponent_defensive_rank - league_avg_defensive_rank
        adjustment = max(-0.15, min(0.15, rank_delta / league_avg_defensive_rank * 0.3))
        rolling_projection *= 1.0 + adjustment

    values_only = [g.fantasy_points for g in sorted_games]
    variance = sum((v - rolling_projection) ** 2 for v in values_only) / len(values_only)
    std_dev = variance**0.5

    if n >= 2:
        recent_avg = sum(g.fantasy_points for g in sorted_games[: min(3, n)]) / min(3, n)
        older = sorted_games[min(3, n) :]
        older_avg = (
            sum(g.fantasy_points for g in older) / len(older) if older else recent_avg
        )
        if recent_avg > older_avg * 1.1:
            trend = "rising"
        elif recent_avg < older_avg * 0.9:
            trend = "falling"
        else:
            trend = "stable"
    else:
        trend = "stable"

    confidence = "high" if n >= 8 else "medium" if n >= 3 else "low"

    return ProjectionResult(
        projected_points=round(rolling_projection, 2),
        floor=round(max(0.0, rolling_projection - std_dev), 2),
        ceiling=round(rolling_projection + std_dev, 2),
        trend=trend,
        games_used=n,
        confidence=confidence,
    )
