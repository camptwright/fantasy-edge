"""Chronological backtest: win rate, ROI, CLV, Brier score. No lookahead -
same walk-forward structure as train_models.py (pre-game ELO prediction
captured before that game's result updates the ratings).

IMPORTANT LIMITATION: ROI and CLV require the market's own odds for a game,
and this system only starts recording odds (via OddsMonitor, `odds_snapshots`)
from whenever it starts running live - constraint #4/#5 do not provide any
historical odds archive, and The Odds API's free tier does not expose one.
Games seeded by `scripts/seed_historical.py` almost always have ZERO
`odds_snapshots` rows, since they finished before this system existed. This
script therefore reports win-rate/Brier (pure result-vs-prediction, needs no
market data) unconditionally, and ROI/CLV only over the subset of games that
happen to have recorded odds - with an explicit coverage count, so the
absence of a number is never silently mistaken for a zero.

Usage:
    python -m scripts.backtest --sport nfl --seasons 2023 2024
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from config.settings import get_sport_config
from src.algorithms import elo
from src.algorithms.clv import aggregate_clv, calculate_clv
from src.algorithms.ev_calculator import evaluate
from src.algorithms.kelly import fractional_kelly_stake
from src.data.cache.db_client import get_worker_db
from src.models.orm import Game, OddsSnapshot
from src.utils.logging import get_logger

log = get_logger(__name__)


async def _load_completed_games(sport: str, seasons: list[int]) -> list[Game]:
    async with get_worker_db() as db:
        result = await db.execute(
            select(Game)
            .where(
                Game.sport == sport,
                Game.status == "final",
                Game.season.in_(seasons),
                Game.home_score.is_not(None),
                Game.away_score.is_not(None),
            )
            .order_by(Game.created_at.asc())
        )
        return list(result.scalars().all())


async def _entry_and_closing_h2h_prices(
    game_id: str,
) -> tuple[dict[str, float], dict[str, float]] | None:
    """(entry_prices, closing_prices) per outcome for this game's h2h market.

    "Entry" = the earliest recorded snapshot, used as a proxy for "the price
    we would have bet at"; "closing" = the latest recorded snapshot before
    the game. CLV compares the two. If OddsMonitor only ever captured one
    snapshot for this game (common right after this system goes live, before
    enough polling cycles have accumulated), entry and closing are the same
    snapshot and CLV is correctly 0 - there was no line movement to
    measure, not a bug.
    """
    async with get_worker_db() as db:
        result = await db.execute(
            select(OddsSnapshot)
            .where(
                OddsSnapshot.game_id == game_id,
                OddsSnapshot.market == "h2h",
            )
            .order_by(OddsSnapshot.captured_at.asc())
        )
        snapshots = result.scalars().all()
    if not snapshots:
        return None

    entry_prices: dict[str, float] = {}
    closing_prices: dict[str, float] = {}
    for snap in snapshots:
        if snap.price_american is None:
            continue
        if snap.outcome not in entry_prices:
            entry_prices[snap.outcome] = snap.price_american
        closing_prices[snap.outcome] = snap.price_american  # last write wins

    if len(entry_prices) < 2 or len(closing_prices) < 2:
        return None
    return entry_prices, closing_prices


async def run(sport: str, seasons: list[int]) -> None:
    games = await _load_completed_games(sport, seasons)
    if not games:
        raise SystemExit(f"no completed games for sport={sport} seasons={seasons}")

    cfg = get_sport_config(sport)
    elo_cfg = elo.EloConfig(**cfg["elo"])
    state = elo.EloState(config=elo_cfg)
    ev_threshold = cfg.get("ev_threshold_pct", 2.0)

    correct = 0
    brier_sum = 0.0
    evaluated = 0
    clv_values: list[float] = []
    total_units_staked = 0.0
    total_units_returned = 0.0
    games_with_odds = 0

    for game in games:
        if game.home_team_id is None or game.away_team_id is None:
            continue

        pre_game = elo.predict(
            state, home_team_id=str(game.home_team_id), away_team_id=str(game.away_team_id)
        )
        home_win_prob = pre_game["home_win_probability"]
        actual_home_win = 1 if game.home_score > game.away_score else 0

        predicted_home_win = 1 if home_win_prob >= 0.5 else 0
        correct += int(predicted_home_win == actual_home_win)
        brier_sum += (home_win_prob - actual_home_win) ** 2
        evaluated += 1

        odds = await _entry_and_closing_h2h_prices(str(game.id))
        if odds:
            entry_prices, closing_prices = odds
            games_with_odds += 1

            def _side_price(prices: dict[str, float], home_name: str) -> tuple[float, float]:
                (side_a, price_a), (side_b, price_b) = list(prices.items())
                if side_a == home_name:
                    return price_a, price_b
                return price_b, price_a

            entry_home_price, entry_away_price = _side_price(
                entry_prices, game.home_team_name or ""
            )
            closing_home_price, _closing_away_price = _side_price(
                closing_prices, game.home_team_name or ""
            )

            # Bet sizing and EV use the ENTRY price - that's the price we'd
            # actually have gotten. Comparing against closing is what CLV is
            # for, done separately below.
            ev_result = evaluate(
                home_win_prob, entry_home_price, entry_away_price, ev_threshold_pct=ev_threshold
            )
            if ev_result.tier != "none":
                stake = fractional_kelly_stake(home_win_prob, entry_home_price, bankroll=1.0)
                total_units_staked += stake
                if actual_home_win:
                    from src.utils.odds_math import american_to_decimal

                    total_units_returned += stake * (
                        american_to_decimal(entry_home_price) - 1.0
                    )
                else:
                    total_units_returned -= stake

            clv = calculate_clv(entry_home_price, closing_home_price)
            clv_values.append(clv.clv_percent)

        elo.update(
            state,
            home_team_id=str(game.home_team_id),
            away_team_id=str(game.away_team_id),
            home_score=game.home_score,
            away_score=game.away_score,
        )

    win_rate = correct / evaluated if evaluated else 0.0
    brier = brier_sum / evaluated if evaluated else 0.0
    roi_pct = (
        (total_units_returned / total_units_staked * 100.0) if total_units_staked > 0 else None
    )
    clv_summary = aggregate_clv(clv_values)

    print(f"Backtest: sport={sport} seasons={seasons} games={evaluated}")
    print(f"  Win rate (favorite-pick accuracy): {win_rate * 100:.1f}%")
    print(f"  Brier score (lower is better-calibrated): {brier:.4f}")
    print(f"  Games with recorded market odds: {games_with_odds}/{evaluated}")
    if roi_pct is not None:
        print(f"  ROI on Kelly-staked bets (odds-covered games only): {roi_pct:.1f}%")
    else:
        print("  ROI: n/a - no games in this range have recorded odds_snapshots")
    if clv_summary["count"]:
        print(
            f"  CLV: mean={clv_summary['mean_clv_percent']:.2f}% "
            f"beat_rate={clv_summary['beat_rate_percent']:.1f}% "
            f"(n={clv_summary['count']})"
        )
    else:
        print("  CLV: n/a - no games in this range have recorded odds_snapshots")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", required=True)
    parser.add_argument("--seasons", nargs="+", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.sport, args.seasons))


if __name__ == "__main__":
    main()
