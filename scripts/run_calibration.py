"""Offline calibration check. Runs on the training host, not reekserver-1,
same as scripts/bootstrap_ratings.py / ingest_history.py - a manual/occasional
tool, not a scheduled task, since it only makes sense to re-run after enough
new finished games have accumulated to move the answer.

Walks src/services/backtest.py's walk-forward simulation for one sport across
the requested seasons, computes Brier score and log loss per market
(moneyline always; spread/total only where real closing lines exist - see
that module's own docstring), and writes one CalibrationReport row per
market that actually produced predictions. A market with zero predictions
(e.g. NCAAF spread/total before any TeamMarketLine rows exist for it) is
skipped entirely rather than written as a fabricated zero-sample report.

passed_gate threshold: brier_score below 0.23 (candidate baselines commonly
cited on real sports betting markets sit in the 0.22-0.24 range; a flat
50%-every-game predictor scores exactly 0.25) AND sample_size >= 50 - a
report from a handful of games is not trustworthy regardless of its score,
matching the same "omit rather than assume" discipline the Elo/totals
baselines themselves already apply to small samples
(MIN_GAMES_FOR_TOTALS/MIN_GAMES_FOR_PROJECTION).
"""

from __future__ import annotations

import argparse
import asyncio

from src.db.client import get_worker_db
from src.models.governance import CalibrationReport
from src.services.backtest import brier_score, log_loss, run_backtest

BRIER_GATE = 0.23
MIN_SAMPLE_SIZE = 50


async def _run(sport: str, seasons: list[int]) -> None:
    async with get_worker_db() as db:
        predictions = await run_backtest(db, sport, seasons)

        by_market: dict[str, list] = {}
        for p in predictions:
            by_market.setdefault(p.market, []).append(p)

        if not by_market:
            print(f"{sport}: no predictions produced - no finished games or closing lines for {seasons}")
            return

        for market, rows in by_market.items():
            brier = brier_score(rows)
            loss = log_loss(rows)
            passed = brier is not None and brier < BRIER_GATE and len(rows) >= MIN_SAMPLE_SIZE
            db.add(
                CalibrationReport(
                    sport=sport,
                    market=market,
                    seasons_used=seasons,
                    sample_size=len(rows),
                    brier_score=brier,
                    log_loss=loss,
                    passed_gate=passed,
                )
            )
            print(
                f"{sport}/{market}: n={len(rows)} brier={brier:.4f} log_loss={loss:.4f} "
                f"passed_gate={passed}"
            )
        await db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True)
    parser.add_argument("--seasons", type=int, nargs="+", required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.sport, args.seasons))


if __name__ == "__main__":
    main()
