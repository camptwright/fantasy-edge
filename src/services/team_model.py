"""NFL team model v2: a points-scale rating rebuilt from published methods.

Reconstructed (no code copied) from:
- FiveThirtyEight's NFL Elo methodology: margin-aware updates, offseason
  reversion toward average, home field, rest differences.
- nfelo's open methodology: log-scaled error updates; "market resist" - when
  the closing line was closer to the result than the model, the model moves
  further; and regression of the model's line toward the market with a
  logistic curve in disagreement (small disagreements collapse to the market,
  large ones keep a bounded opinion).

Ratings are in points (team strength above an average team). Pure functions
with stdlib math only, shared by the serving path and the offline research
backtest (scripts/research_game_model.py) so both run identical math.
Parameters and the starting ratings are fitted offline into
config/nfl_team_model.json; see docs for the walk-forward evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path

from src.utils.odds_math import normal_cdf

CONFIG = Path(__file__).resolve().parents[2] / "config" / "nfl_team_model.json"
# nflverse historical franchise codes -> current codes.
RELOCATED = {"OAK": "LV", "SD": "LAC", "STL": "LAR", "LA": "LAR"}


@dataclass(frozen=True)
class Params:
    k: float = 0.45            # update size per log-point of model error
    resist: float = 2.0        # points of "market was closer" error that doubles the update
    reversion: float = 0.3     # offseason pull toward average
    hfa: float = 2.0           # home field, points
    rest: float = 0.2          # points per day of rest advantage (clipped to +/-7 days)
    sigma: float = 13.5        # margin standard deviation for probabilities
    mr_mid: float = 2.0        # model/market disagreement (points) at the curve's midpoint
    mr_steep: float = 2.0      # steepness of the market-regression curve
    mr_floor: float = 0.75     # weight on the market for large disagreements

    @classmethod
    def from_dict(cls, raw: dict) -> "Params":
        names = {f.name for f in fields(cls)}
        return cls(**{k: float(v) for k, v in raw.items() if k in names})


def expected_margin(p: Params, home: float, away: float, *, neutral: bool = False, rest_diff: float = 0.0) -> float:
    """Model home margin before any market input."""
    return home - away + (0.0 if neutral else p.hfa) + p.rest * max(-7.0, min(7.0, rest_diff))


def update(p: Params, home: float, away: float, expected: float, margin: float,
           closing_spread: float | None) -> tuple[float, float]:
    """Post-game ratings. `closing_spread` is the market's home expected margin (None if unknown)."""
    model_err = abs(margin - expected)
    k = p.k
    if closing_spread is not None:
        market_err = abs(margin - closing_spread)
        if model_err > max(1.0, market_err):
            k *= 1 + (model_err - market_err) / p.resist
    shift = k * math.copysign(math.log1p(model_err), margin - expected)
    return home + shift / 2, away - shift / 2


def rollover(p: Params, ratings: dict[str, float]) -> dict[str, float]:
    return {team: (1 - p.reversion) * value for team, value in ratings.items()}


def market_weight(p: Params, model: float, market: float) -> float:
    d = abs(model - market)
    z = max(-50.0, min(50.0, p.mr_steep * (d - p.mr_mid)))
    return p.mr_floor + (1 - p.mr_floor) / (1 + math.exp(z))


def regress_to_market(p: Params, model: float, market: float | None) -> float:
    return model if market is None else model + market_weight(p, model, market) * (market - model)


def win_probability(p: Params, margin: float) -> float:
    return normal_cdf(margin / p.sigma)


def cover_probability(p: Params, margin: float, home_line: float) -> float:
    """P(home covers `home_line`), sportsbook convention (negative = home favoured)."""
    return 1.0 - normal_cdf((-home_line - margin) / p.sigma)


def over_probability(p: Params, expected_total: float, line: float, total_sigma: float) -> float:
    return 1.0 - normal_cdf((line - expected_total) / total_sigma)


@lru_cache(maxsize=1)
def load() -> dict | None:
    """The fitted artifact: params, starting ratings (current codes) and its evidence."""
    if not CONFIG.exists():
        return None
    text = CONFIG.read_text()
    raw = json.loads(text)
    version = f"{raw['recipe']}:{hashlib.sha256(text.encode()).hexdigest()[:12]}"
    return {**raw, "version": version, "params": Params.from_dict(raw["params"])}
