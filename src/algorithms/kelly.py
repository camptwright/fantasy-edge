"""Kelly criterion bet sizing: full, fractional, and portfolio (multi-bet).

The default everywhere in this codebase is quarter-Kelly
(`settings.kelly_fraction = 0.25`), because full Kelly is famously the
optimal *log-growth* strategy only under the model's assumptions being
exactly correct - and a statistical model's edge estimate is always noisy.
Betting the full Kelly fraction against a noisy edge estimate produces wild
bankroll swings and a real chance of over-betting when the model is simply
wrong. Quarter-Kelly trades some long-run growth for a much shorter drawdown
tail, which is the right trade for a system whose edge is a model output,
not a certainty.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.utils.odds_math import american_to_decimal


def full_kelly_fraction(model_probability: float, american_price: float) -> float:
    """Fraction of bankroll to stake, before any fractional scaling.

    f* = (b*p - q) / b, where b = net decimal odds (payout per unit staked),
    p = true win probability, q = 1 - p.

    A negative result means the bet has no edge (or negative edge) at this
    price - callers should treat negative/zero as "don't bet", not stake a
    negative amount.
    """
    decimal_odds = american_to_decimal(american_price)
    b = decimal_odds - 1.0
    if b <= 0:
        return 0.0
    q = 1.0 - model_probability
    f_star = (b * model_probability - q) / b
    return f_star


def fractional_kelly_stake(
    model_probability: float,
    american_price: float,
    *,
    fraction: float = 0.25,
    bankroll: float = 1.0,
    max_stake_fraction: float = 0.05,
) -> float:
    """Stake in bankroll units, e.g. bankroll=1.0 returns a fraction of
    bankroll; bankroll=1000.0 returns dollars.

    `max_stake_fraction` is a hard cap independent of the Kelly math - a
    single mis-estimated edge (bad data, a stale rating) should never be
    able to size a bet at, say, 40% of bankroll just because the formula
    says so. This is the "don't trust the model blindly" backstop.
    """
    f_star = full_kelly_fraction(model_probability, american_price)
    if f_star <= 0:
        return 0.0
    scaled = f_star * fraction
    capped = min(scaled, max_stake_fraction)
    return capped * bankroll


@dataclass
class PortfolioBet:
    key: str
    model_probability: float
    american_price: float


def portfolio_kelly_stakes(
    bets: list[PortfolioBet],
    *,
    fraction: float = 0.25,
    bankroll: float = 1.0,
    max_total_exposure: float = 0.25,
    max_stake_fraction: float = 0.05,
) -> dict[str, float]:
    """Size multiple simultaneous bets (e.g. today's full slate).

    Independent per-bet fractional Kelly ignores that a bankroll can't
    actually be staked more than once at the same time - if five games each
    ask for 5% of bankroll, that's 25% of bankroll live at once, not
    unlimited. `max_total_exposure` scales every stake down proportionally
    (not per-bet-capped independently) if the naive sum would exceed it, so
    the highest-edge bets still get the largest share of the reduced budget.
    """
    raw_stakes: dict[str, float] = {}
    for bet in bets:
        stake = fractional_kelly_stake(
            bet.model_probability,
            bet.american_price,
            fraction=fraction,
            bankroll=bankroll,
            max_stake_fraction=max_stake_fraction,
        )
        if stake > 0:
            raw_stakes[bet.key] = stake

    total = sum(raw_stakes.values())
    max_allowed = max_total_exposure * bankroll
    if total <= max_allowed or total == 0:
        return raw_stakes

    scale = max_allowed / total
    return {key: stake * scale for key, stake in raw_stakes.items()}
