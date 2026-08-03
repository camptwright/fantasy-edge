"""Odds conversions and vig removal.

Kept free of database and network imports so it can be unit-tested in
isolation and imported by both providers (at ingest) and the EV calculator.

American odds are the storage format because that is what every US book
publishes and what the user reads. Decimal is the computation format because
payout maths is multiplicative. Implied probability is decimal reciprocal.
"""

from __future__ import annotations


def american_to_decimal(american: float) -> float:
    """-110 -> 1.9091, +150 -> 2.50.

    American 0 is not a real price; treat it as even money rather than
    dividing by zero.
    """
    if american == 0:
        return 2.0
    if american > 0:
        return 1.0 + (american / 100.0)
    return 1.0 + (100.0 / abs(american))


def decimal_to_american(decimal: float) -> int:
    """Inverse of american_to_decimal, rounded to the nearest whole number."""
    if decimal <= 1.0:
        # Sub-1.0 decimal odds are nonsense (negative payout); clamp rather
        # than emit a wild number that looks like a real price.
        return -100000
    if decimal >= 2.0:
        return int(round((decimal - 1.0) * 100.0))
    return int(round(-100.0 / (decimal - 1.0)))


def american_to_implied(american: float) -> float:
    """Implied probability INCLUDING the book's vig. Range (0, 1)."""
    return 1.0 / american_to_decimal(american)


def decimal_to_implied(decimal: float) -> float:
    if decimal <= 0:
        return 0.0
    return 1.0 / decimal


def probability_to_american(probability: float) -> int:
    """Fair American price for a probability, ignoring vig."""
    if probability <= 0.0 or probability >= 1.0:
        return 0
    return decimal_to_american(1.0 / probability)


# ------------------------------------------------------------------- vig ----


def remove_vig(implied: list[float]) -> list[float]:
    """Proportional (multiplicative) vig removal.

    A two-way market prices to more than 100% - e.g. -110/-110 sums to 1.0476.
    That 4.76% overround is the book's margin. Dividing each side by the sum
    renormalises to a true probability distribution.

    This is the "proportional" method. It is the standard choice and it is
    unbiased for balanced markets, but note it distributes the margin evenly
    across outcomes, which slightly overstates the fair price of heavy
    longshots (books load more vig onto the favourite side in practice). For
    the near-even markets we bet, the error is smaller than our EV threshold.
    """
    total = sum(implied)
    if total <= 0:
        return [0.0 for _ in implied]
    return [p / total for p in implied]


def remove_vig_two_way(price_a: float, price_b: float) -> tuple[float, float]:
    """Convenience wrapper for h2h/spread/total markets. Returns (fair_a, fair_b)."""
    fair = remove_vig([american_to_implied(price_a), american_to_implied(price_b)])
    return fair[0], fair[1]


def overround(implied: list[float]) -> float:
    """Book margin as a percentage. -110/-110 returns ~4.76."""
    return (sum(implied) - 1.0) * 100.0


# -------------------------------------------------------------------- ev ----


def expected_value_percent(model_probability: float, american: float) -> float:
    """EV per unit staked, as a percentage.

    EV = p * (decimal - 1) - (1 - p) * 1

    i.e. win the net payout with probability p, lose the stake otherwise.
    A return of 5.0 means "expect +5 units per 100 staked, long run".
    """
    decimal = american_to_decimal(american)
    ev = model_probability * (decimal - 1.0) - (1.0 - model_probability)
    return ev * 100.0
