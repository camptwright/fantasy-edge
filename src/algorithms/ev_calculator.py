"""Turns (model probability, book price) into a bettable signal: EV%, a
tier, and a confidence read on how much to trust it.

Vig removal (`remove_vig_two_way`, in `src/utils/odds_math.py`) is what makes
"model probability" and "market probability" comparable at all - a raw book
price's implied probability always sums to >100% across a two-way market, so
comparing a model's fair probability against it directly overstates the
model's apparent edge by roughly the vig. This module is where that
comparison actually happens for the purpose of deciding whether to bet.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.utils.odds_math import american_to_implied, expected_value_percent, remove_vig_two_way

# A model that disagrees with the vig-removed market by more than this many
# percentage points is more likely to indicate a data problem (misidentified
# team, stale rating, wrong market matched) than a genuine mispriced line.
# Real, sustainable sports betting edges are usually single digits.
SUSPICIOUS_DIVERGENCE_PCT = 15.0


@dataclass
class EVResult:
    model_probability: float
    market_fair_probability: float
    market_implied_probability: float
    ev_percent: float
    edge_percent: float  # model - fair market, in probability percentage points
    tier: str  # none | standard | strong | elite
    confidence: str  # low | medium | high
    is_suspicious: bool


def evaluate(
    model_probability: float,
    american_price: float,
    opposing_american_price: float,
    *,
    ev_threshold_pct: float,
) -> EVResult:
    """`opposing_american_price` is the other side of the same two-way
    market (the other h2h outcome, or over vs under) - needed to remove vig,
    since a single price alone doesn't reveal the book's margin.
    """
    fair_this_side, _fair_other_side = remove_vig_two_way(
        american_price, opposing_american_price
    )
    market_implied = american_to_implied(american_price)

    ev_percent = expected_value_percent(model_probability, american_price)
    edge_percent = (model_probability - fair_this_side) * 100.0
    is_suspicious = abs(edge_percent) >= SUSPICIOUS_DIVERGENCE_PCT

    if ev_percent < ev_threshold_pct:
        tier = "none"
    elif ev_percent < ev_threshold_pct * 2:
        tier = "standard"
    elif ev_percent < ev_threshold_pct * 4:
        tier = "strong"
    else:
        tier = "elite"

    if is_suspicious:
        confidence = "low"
    elif abs(edge_percent) < 5.0:
        confidence = "high"
    else:
        confidence = "medium"

    return EVResult(
        model_probability=model_probability,
        market_fair_probability=fair_this_side,
        market_implied_probability=market_implied,
        ev_percent=ev_percent,
        edge_percent=edge_percent,
        tier=tier,
        confidence=confidence,
        is_suspicious=is_suspicious,
    )
