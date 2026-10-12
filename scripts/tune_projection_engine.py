"""Walk-forward hyperparameter search for projection engine v1.

Run in the worker environment:
    python -m scripts.tune_projection_engine [--league LEAGUE_ID]

Each evaluated week is projected only from games that kicked off before
that week's first kickoff, with each target game's own kickoff-time line.
Error is absolute league-scored points (the chosen Sleeper league's
scoring) for players who actually played, on FantasyPros' in-season pool:
each position's top-N by projection or by actual result that week.

Selection protocol, reported side by side:
- `holdout`: parameters chosen on 2025 only, then scored on 2026 untouched.
- `combined`: parameters chosen on 2025 + 2026 (owner-directed 2026-10-12).
Choosing on 2026 makes any later retrospective 2026 comparison with Sleeper
in-sample; prospective capture from the new version onward is unaffected.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import select

from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.sleeper import SleeperLeague
from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.projection_engine import DEFAULT, Params, compute, load_history, score

POOL = {"QB": 25, "RB": 50, "WR": 60, "TE": 20}  # FantasyPros in-season pool sizes
WEEKS = [(2025, w) for w in range(4, 19)] + [(2026, w) for w in range(2, 7)]
GRID = {
    "half_life": [2.0, 3.0, 4.0, 6.0],
    "share_prior_games": [0.5, 1.0, 1.5, 3.0],
    "rate_scale": [1.0, 2.0, 4.0],
    "td_scale": [0.5, 1.0, 2.0],
    "share_prior_quantile": [0.1, 0.25, 0.5],
}


def week_slates(history):
    """(season, week) -> (cutoff, targets, actual player-games)."""
    by_week = defaultdict(list)
    for g in history.games.values():
        by_week[(g.season, g.week)].append(g)
    slates = {}
    for key in WEEKS:
        games = by_week.get(key, [])
        targets = []
        for g in games:
            home = history.teams.get((g.id, g.home_team_id))
            away = history.teams.get((g.id, g.away_team_id))
            if home and away and home.implied_points is not None and away.implied_points is not None:
                targets.append((g, home.implied_points, away.implied_points, home.spread))
        if targets:
            ids = {g.id for g, *_ in targets}
            actual = {p.player_id: p for p in history.players.values() if p.game_id in ids}
            slates[key] = (min(g.game_time for g, *_ in targets), targets, actual)
    return slates


def evaluate(history, slates, weights_by_stat, params, keys):
    pool_errors, all_errors, pool_bias = [], [], []
    by_position = defaultdict(list)
    for key in keys:
        cutoff, targets, actual = slates[key]
        projections = compute(history, targets, cutoff, params)
        rows = defaultdict(list)
        for player_id, proj in projections.items():
            played = actual.get(player_id)
            if played is None or played.game_id != proj.game_id:
                continue  # did not play: availability is not this model's job
            rows[proj.position].append((score(proj.stats, weights_by_stat), score(played.stats, weights_by_stat)))
        for position, pairs in rows.items():
            n = POOL[position]
            keep = set(sorted(range(len(pairs)), key=lambda i: -pairs[i][0])[:n])
            keep |= set(sorted(range(len(pairs)), key=lambda i: -pairs[i][1])[:n])
            for i, (p, a) in enumerate(pairs):
                all_errors.append(abs(p - a))
                if i in keep:
                    pool_errors.append(abs(p - a))
                    pool_bias.append(p - a)
                    by_position[position].append(abs(p - a))
    return {"pool_mae": float(np.mean(pool_errors)), "all_mae": float(np.mean(all_errors)),
            "pool_bias": float(np.mean(pool_bias)), "n_pool": len(pool_errors),
            "by_position_pool_mae": {p: round(float(np.mean(v)), 3) for p, v in sorted(by_position.items())}}


async def run(league_id: str | None) -> dict:
    async with get_worker_db() as db:
        leagues = (await db.scalars(select(SleeperLeague).where(SleeperLeague.platform == "sleeper"))).all()
        league = next(lg for lg in leagues if league_id in (None, lg.league_id))
        history = await load_history(db, [2024, 2025, 2026], datetime.now(timezone.utc))
    weights_by_stat = {CORE[k]: w for k, w in offensive_weights(league.scoring_settings).items() if k in CORE}
    slates = week_slates(history)
    seasons = {season: [k for k in slates if k[0] == season] for season in (2025, 2026)}
    combos = [Params(**dict(zip(GRID, values))) for values in itertools.product(*GRID.values())]
    results = []
    for params in combos:
        results.append({"params": asdict(params),
                         "2025": evaluate(history, slates, weights_by_stat, params, seasons[2025]),
                         "2026": evaluate(history, slates, weights_by_stat, params, seasons[2026])})
    n25, n26 = (sum(1 for _ in seasons[s]) for s in (2025, 2026))

    def combined(r):
        w25, w26 = r["2025"]["n_pool"], r["2026"]["n_pool"]
        return (r["2025"]["pool_mae"] * w25 + r["2026"]["pool_mae"] * w26) / (w25 + w26)

    default = next(r for r in results if r["params"] == asdict(DEFAULT))
    holdout = min(results, key=lambda r: r["2025"]["pool_mae"])
    best = min(results, key=combined)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(), "league_id": league.league_id,
        "weeks": {"2025": n25, "2026": n26}, "combos": len(results),
        "default": {**default, "combined_pool_mae": round(combined(default), 3)},
        "holdout_choice": {**holdout, "combined_pool_mae": round(combined(holdout), 3)},
        "combined_choice": {**best, "combined_pool_mae": round(combined(best), 3)},
        "scope": "Walk-forward on stored stats; selection protocol in module docstring.",
    }
    out = Path(get_settings().raw_archive_dir) / "projection-engine" / "tuning"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json").write_text(
        json.dumps({**report, "all": results}, indent=1))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.league)), indent=1))


if __name__ == "__main__":
    main()
