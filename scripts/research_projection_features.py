"""Walk-forward experiments for projection-engine features, outside the engine.

Features are applied to compute()'s output so projection_engine.py (and its
prospective version hash) is untouched until a feature earns its place.
Selection protocol: settings chosen on 2025 weeks only, then scored on 2026
weeks untouched (the `holdout` protocol of scripts/tune_projection_engine.py).

Feature 1 - opponent adjustment (4for4 "adjusted fantasy points allowed",
FantasyPros/PFF matchup ratings): each defense's efficiency allowed to a
position over its recent games, shrunk toward the league with
pseudo-opportunities, scales the player's efficiency-driven stats by
(allowed / league) ** weight. Volume is untouched: Vegas totals and the
spread already carry opponent strength into team volume.

Run in the worker environment:
    python -m scripts.research_projection_features [--league LEAGUE_ID]
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select

from src.db.client import get_worker_db
from src.models.sleeper import SleeperLeague
from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.projection_engine import DEFAULT, compute, load_history, score
from scripts.tune_projection_engine import POOL, week_slates

DEFENSE_LOOKBACK = 12  # defensive games
# (stat scaled, numerator, denominator) allowed by a defense to a position.
ALLOWED = {
    "receptions": ("receptions", "targets"),
    "receiving_yards": ("receiving_yards", "targets"),
    "receiving_touchdowns": ("receiving_touchdowns", "targets"),
    "rushing_yards": ("rushing_yards", "rushing_attempts"),
    "rushing_touchdowns": ("rushing_touchdowns", "rushing_attempts"),
    "passing_yards": ("passing_yards", "passing_attempts"),
    "passing_touchdowns": ("passing_touchdowns", "passing_attempts"),
    "passing_interceptions": ("passing_interceptions", "passing_attempts"),
}
TD_STATS = {"receiving_touchdowns", "rushing_touchdowns", "passing_touchdowns", "passing_interceptions"}


def opponent_of(history, game_id, team_id):
    g = history.games[game_id]
    return g.away_team_id if team_id == g.home_team_id else g.home_team_id


def defense_factors(history, cutoff, pseudo, td_pseudo):
    """(defense team, position) -> {stat: allowed/league ratio}, from games before cutoff."""
    rows = [p for p in history.players.values() if p.kickoff < cutoff and history.positions.get(p.player_id) in POOL]
    league = defaultdict(lambda: defaultdict(float))
    by_defense = defaultdict(lambda: defaultdict(float))
    games_of = defaultdict(set)
    for p in rows:
        games_of[opponent_of(history, p.game_id, p.team_id)].add((p.kickoff, p.game_id))
    recent = {d: {gid for _, gid in sorted(gs)[-DEFENSE_LOOKBACK:]} for d, gs in games_of.items()}
    for p in rows:
        pos = history.positions[p.player_id]
        d = opponent_of(history, p.game_id, p.team_id)
        for num, den in ALLOWED.values():
            for key in (num, den):
                league[pos][key] += p.stats.get(key, 0.0)
                if p.game_id in recent[d]:
                    by_defense[(d, pos)][key] += p.stats.get(key, 0.0)
    out = {}
    for (d, pos), sums in by_defense.items():
        f = {}
        for stat, (num, den) in ALLOWED.items():
            if not league[pos][den]:
                continue
            base = league[pos][num] / league[pos][den]
            k = td_pseudo if stat in TD_STATS else pseudo
            shrunk = (sums[num] + k * base) / (sums[den] + k)
            f[stat] = shrunk / base if base > 0 else 1.0
        out[(d, pos)] = f
    return out


def evaluate(history, slates, weights, keys, *, weight=0.0, pseudo=200.0, td_pseudo=600.0):
    pool_errors, by_position = [], defaultdict(list)
    for key in keys:
        cutoff, targets, actual = slates[key]
        projections = compute(history, targets, cutoff, DEFAULT)
        factors = defense_factors(history, cutoff, pseudo, td_pseudo) if weight else {}
        rows = defaultdict(list)
        for player_id, proj in projections.items():
            played = actual.get(player_id)
            if played is None or played.game_id != proj.game_id:
                continue
            stats = dict(proj.stats)
            f = factors.get((opponent_of(history, proj.game_id, proj.team_id), proj.position), {})
            for stat, ratio in f.items():
                stats[stat] = stats.get(stat, 0.0) * ratio ** weight
            rows[proj.position].append((score(stats, weights), score(played.stats, weights)))
        for position, pairs in rows.items():
            n = POOL[position]
            keep = set(sorted(range(len(pairs)), key=lambda i: -pairs[i][0])[:n])
            keep |= set(sorted(range(len(pairs)), key=lambda i: -pairs[i][1])[:n])
            for i, (p, a) in enumerate(pairs):
                if i in keep:
                    pool_errors.append(abs(p - a))
                    by_position[position].append(abs(p - a))
    return {"pool_mae": round(float(np.mean(pool_errors)), 4), "n_pool": len(pool_errors),
            "by_position": {p: round(float(np.mean(v)), 3) for p, v in sorted(by_position.items())}}


async def run(league_id):
    async with get_worker_db() as db:
        leagues = (await db.scalars(select(SleeperLeague).where(SleeperLeague.platform == "sleeper"))).all()
        league = next(lg for lg in leagues if league_id in (None, lg.league_id))
        history = await load_history(db, [2024, 2025, 2026], datetime.now(timezone.utc))
    weights = {CORE[k]: w for k, w in offensive_weights(league.scoring_settings).items() if k in CORE}
    slates = week_slates(history)
    seasons = {s: [k for k in slates if k[0] == s] for s in (2025, 2026)}
    grid = [{"weight": w, "pseudo": p, "td_pseudo": t} for w, p, t in
            itertools.product([0.25, 0.5, 0.75, 1.0], [100.0, 300.0, 800.0], [300.0, 1200.0])]
    baseline = {s: evaluate(history, slates, weights, seasons[s]) for s in (2025, 2026)}
    results = [{"setting": g, "2025": evaluate(history, slates, weights, seasons[2025], **g)} for g in grid]
    best = min(results, key=lambda r: r["2025"]["pool_mae"])
    best["2026"] = evaluate(history, slates, weights, seasons[2026], **best["setting"])
    return {"feature": "opponent_adjustment", "baseline": baseline, "chosen_on_2025": best,
            "top_2025": sorted(results, key=lambda r: r["2025"]["pool_mae"])[:5]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league")
    print(json.dumps(asyncio.run(run(ap.parse_args().league)), indent=1))


if __name__ == "__main__":
    main()
