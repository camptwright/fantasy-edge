"""Sport-specific ELO ratings.

Each sport's volatility (K), home advantage, margin-of-victory weighting, and
between-season regression live in `config/sports.yaml` (constraint: config
drives sport differences, not code branches) - this module is the same math
for every sport, parameterised by that config.

The MOV multiplier follows FiveThirtyEight's NFL formula generalised: a
blowout should move ratings more than a squeaker, but the effect must taper
off (a 40-point margin shouldn't move a rating 4x as much as a 10-point one)
and it must shrink as the rating gap that "explains" the margin grows, or a
team already expected to win big gets over-rewarded for doing exactly that.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

DEFAULT_RATING = 1500.0


@dataclass
class EloConfig:
    k: float
    home_advantage: float = 0.0
    mov_multiplier: float = 1.0
    season_regression: float = 0.0


@dataclass
class EloState:
    """Rolling ratings for one sport, keyed by team id."""

    config: EloConfig
    ratings: dict[str, float] = field(default_factory=dict)

    def get(self, team_id: str) -> float:
        return self.ratings.get(team_id, DEFAULT_RATING)

    def regress_to_mean(self) -> None:
        """Called once between seasons. Pulls every rating toward 1500 by
        `season_regression`, so a team's reputation from two years ago
        doesn't linger forever - rosters turn over."""
        frac = self.config.season_regression
        for team_id, rating in self.ratings.items():
            self.ratings[team_id] = rating + (DEFAULT_RATING - rating) * frac


def win_probability(rating_a: float, rating_b: float) -> float:
    """Standard logistic ELO expectation. 400 = the classic "one full
    letter grade" scaling every ELO implementation since chess has used."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def _mov_multiplier(margin: float, elo_diff: float, base_multiplier: float) -> float:
    """FiveThirtyEight-style margin-of-victory scaling.

    ln(|margin| + 1) makes the effect of margin logarithmic (a 21-point win
    is not 3x as informative as a 7-point win). Dividing by
    (2.2 + 0.001 * elo_diff) dampens the boost when the winner was already
    heavily favoured - beating a bad team by a lot is expected, not new
    information.
    """
    if base_multiplier == 0.0:
        return 1.0
    return base_multiplier * math.log(abs(margin) + 1.0) / (2.2 + 0.001 * abs(elo_diff))


def update(
    state: EloState,
    *,
    home_team_id: str,
    away_team_id: str,
    home_score: int,
    away_score: int,
) -> tuple[float, float]:
    """Applies one completed game's result. Returns (new_home_rating,
    new_away_rating). Mutates `state.ratings` in place."""
    home_rating = state.get(home_team_id)
    away_rating = state.get(away_team_id)

    home_rating_with_hfa = home_rating + state.config.home_advantage
    expected_home = win_probability(home_rating_with_hfa, away_rating)

    margin = home_score - away_score
    if margin > 0:
        actual_home = 1.0
    elif margin < 0:
        actual_home = 0.0
    else:
        actual_home = 0.5

    elo_diff = home_rating_with_hfa - away_rating
    mult = _mov_multiplier(margin, elo_diff, state.config.mov_multiplier)

    delta = state.config.k * mult * (actual_home - expected_home)
    new_home = home_rating + delta
    new_away = away_rating - delta

    state.ratings[home_team_id] = new_home
    state.ratings[away_team_id] = new_away
    return new_home, new_away


def predict(
    state: EloState, *, home_team_id: str, away_team_id: str
) -> dict[str, float]:
    """Pre-game win probabilities without mutating state. Used both live
    (ValueAgent) and in backtests (which must never call `update` before
    the corresponding prediction - constraint: no lookahead)."""
    home_rating = state.get(home_team_id) + state.config.home_advantage
    away_rating = state.get(away_team_id)
    home_win = win_probability(home_rating, away_rating)
    return {"home_win_probability": home_win, "away_win_probability": 1.0 - home_win}
