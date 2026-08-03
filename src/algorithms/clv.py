"""Closing line value: the pure math. `src/agents/clv_tracker.py` (Phase 4)
owns finding the closing price in the DB and writing the result back onto a
`BetSignal`; this module only knows how to compare two prices.

CLV is the honest long-run scoreboard for a betting model, more honest than
win rate: a model can go on a losing streak from pure variance while still
consistently beating the closing line (a strong signal the underlying edge
is real), or it can go on a winning streak from luck while consistently
getting worse prices than the close (a red flag the "edge" is noise). Prices
tend toward efficiency as game time approaches - the closing line reflects
the most information the market will ever have - so beating it means you
identified the mispricing before the market corrected.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.utils.odds_math import american_to_decimal


@dataclass
class ClvResult:
    clv_percent: float
    beat_closing_line: bool


def calculate_clv(bet_price_american: float, closing_price_american: float) -> ClvResult:
    """Positive `clv_percent` means the price taken at bet time paid out
    more than the closing price would have for an identical win - i.e. the
    market moved toward the bettor's side after the bet was placed.

    Computed on decimal odds rather than implied probability because it's a
    statement about payout quality ("how much better a price did I get"),
    which decimal odds represent directly and probability does not.
    """
    bet_decimal = american_to_decimal(bet_price_american)
    closing_decimal = american_to_decimal(closing_price_american)
    if closing_decimal <= 0:
        return ClvResult(clv_percent=0.0, beat_closing_line=False)

    clv_percent = ((bet_decimal - closing_decimal) / closing_decimal) * 100.0
    return ClvResult(clv_percent=clv_percent, beat_closing_line=clv_percent > 0)


def aggregate_clv(clv_percents: list[float]) -> dict[str, float]:
    """Summary stats for a batch of signals - what the model QA dashboard
    (Rankings/backtest report) actually displays."""
    if not clv_percents:
        return {"mean_clv_percent": 0.0, "beat_rate_percent": 0.0, "count": 0}
    beat_count = sum(1 for c in clv_percents if c > 0)
    return {
        "mean_clv_percent": sum(clv_percents) / len(clv_percents),
        "beat_rate_percent": (beat_count / len(clv_percents)) * 100.0,
        "count": len(clv_percents),
    }
