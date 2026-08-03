"""Dixon-Coles bivariate Poisson: score matrix, totals, and spread coverage.

Two independent Poisson processes (home scoring, away scoring) already
capture most of a low/moderate-scoring game, but real matches show a small
excess of 0-0, 1-0, 0-1 and 1-1 results beyond what independent Poissons
predict - teams that are actually tied tend to play a bit more cautiously
right at that scoreline. Dixon & Coles (1997) fix this with a low-score
correlation term `tau(x, y, rho)` applied only to those four cells; away from
the low-score corner the model is unmodified independent Poisson.

`rho` is negative in practice (the correlation dampens joint low scores).
It should ideally be fit per sport via MLE against historical results
(train_models.py's job); here it defaults to a literature-typical value and
can be overridden once a fitted value exists.

This is a soccer-shaped model applied to any "count the scoring events"
sport. It is a good fit for goal-scarce sports (NHL, MLB via runs) and a
rougher approximation for NFL/basketball's higher, more continuous scoring -
which is exactly why `sports.yaml` gives Poisson a low blend weight for NBA
and a higher one for NHL/MLB (see the comments there).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, factorial

DEFAULT_RHO = -0.05


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return exp(-lam) * (lam**k) / factorial(k)


def _tau(x: int, y: int, lambda_home: float, lambda_away: float, rho: float) -> float:
    """Dixon-Coles low-score correction factor. 1.0 everywhere except the
    four cells where a tie/near-tie interacts with home/away scoring."""
    if x == 0 and y == 0:
        return 1.0 - (lambda_home * lambda_away * rho)
    if x == 0 and y == 1:
        return 1.0 + (lambda_home * rho)
    if x == 1 and y == 0:
        return 1.0 + (lambda_away * rho)
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def score_matrix(
    lambda_home: float,
    lambda_away: float,
    *,
    rho: float = DEFAULT_RHO,
    max_score: int = 10,
) -> list[list[float]]:
    """`matrix[home_score][away_score]` = P(that exact scoreline).

    `max_score` should comfortably exceed any realistic score for the sport -
    10 for soccer/hockey-scale, much higher for NFL/NBA-scale totals. Values
    are NOT truncated-and-renormalised; for a well-chosen max_score the
    excluded tail probability is negligible.
    """
    matrix = [[0.0] * (max_score + 1) for _ in range(max_score + 1)]
    for x in range(max_score + 1):
        p_x = _poisson_pmf(x, lambda_home)
        for y in range(max_score + 1):
            p_y = _poisson_pmf(y, lambda_away)
            matrix[x][y] = _tau(x, y, lambda_home, lambda_away, rho) * p_x * p_y
    return matrix


@dataclass
class MatchOutcome:
    home_win: float
    draw: float
    away_win: float


def match_outcome_probabilities(matrix: list[list[float]]) -> MatchOutcome:
    home_win = draw = away_win = 0.0
    for x, row in enumerate(matrix):
        for y, p in enumerate(row):
            if x > y:
                home_win += p
            elif x == y:
                draw += p
            else:
                away_win += p
    return MatchOutcome(home_win=home_win, draw=draw, away_win=away_win)


def total_probabilities(matrix: list[list[float]], line: float) -> dict[str, float]:
    """P(total over/under `line`). `line` is typically a .5 book total, so
    a push (total == line) is impossible for the common case but handled
    for integer lines anyway."""
    over = under = push = 0.0
    for x, row in enumerate(matrix):
        for y, p in enumerate(row):
            total = x + y
            if total > line:
                over += p
            elif total < line:
                under += p
            else:
                push += p
    return {"over": over, "under": under, "push": push}


def spread_probabilities(matrix: list[list[float]], home_line: float) -> dict[str, float]:
    """P(home covers `home_line`). A home favourite has a negative line
    (e.g. -3.5): home covers if (home_score + home_line) > away_score, i.e.
    home wins by more than 3.5. A positive home_line is the underdog case.
    """
    home_covers = away_covers = push = 0.0
    for x, row in enumerate(matrix):
        for y, p in enumerate(row):
            adjusted = x + home_line - y
            if adjusted > 0:
                home_covers += p
            elif adjusted < 0:
                away_covers += p
            else:
                push += p
    return {"home_covers": home_covers, "away_covers": away_covers, "push": push}


def expected_goals_from_ratings(
    home_attack: float,
    home_defense: float,
    away_attack: float,
    away_defense: float,
    league_avg_goals: float,
    *,
    home_advantage_multiplier: float = 1.1,
) -> tuple[float, float]:
    """Standard Dixon-Coles attack/defense parameterisation:
    lambda_home = home_attack * away_defense * league_avg * home_advantage
    lambda_away = away_attack * home_defense * league_avg

    Attack/defense ratings are expected as multiplicative factors around 1.0
    (1.2 = scores 20% more than league average; a defense factor of 0.8 =
    concedes 20% less), which is what `scripts/train_models.py` fits from
    historical scoring data per team.
    """
    lambda_home = home_attack * away_defense * league_avg_goals * home_advantage_multiplier
    lambda_away = away_attack * home_defense * league_avg_goals
    return lambda_home, lambda_away
