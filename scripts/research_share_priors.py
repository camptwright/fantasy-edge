"""Share-prior variants for projection engine v1 (walk-forward, tune_projection_engine harness).

league_priors sets each position's share prior to a quantile of the shares of
players who recorded the stat at all. For off-role stats that prior is a
fringe role: QBs are pulled toward the target share of the few QBs who caught
a pass, WRs/TEs toward a ball-carrier's share (diagnose_projection_engine:
QB receptions + receiving TDs projected +0.46 points a game against actual,
WR rushing +0.23). Variants:
- default: quantile of positive shares;
- zero_aware: that prior times the position's fraction of player-games with
  a positive share (an expected share, not a conditional one);
- off_role: zero_aware only where that fraction is below OFF_ROLE (stats the
  position rarely records), default elsewhere.
Run in the worker environment: python -m scripts.research_share_priors [--league ID]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select

import src.services.projection_engine as engine
from src.db.client import get_worker_db
from src.models.sleeper import SleeperLeague
from src.services.fantasy_decision_models import CORE, offensive_weights
from scripts.tune_projection_engine import evaluate, week_slates

OFF_ROLE = 0.5
original = engine.league_priors


def fractions(players, positions, teams):
    counts = defaultdict(lambda: [0, 0])
    for p in players.values():
        pos = positions.get(p.player_id)
        if pos not in engine.POSITIONS:
            continue
        team = teams[(p.game_id, p.team_id)]
        for stat, team_stat in engine.SHARE_STATS:
            if getattr(team, team_stat) > 0:
                c = counts[(pos, stat)]
                c[0] += p.stats.get(stat, 0.0) > 0
                c[1] += 1
    return {k: a / b for k, (a, b) in counts.items() if b}


def variant(mode):
    def priors(players, positions, teams, params=engine.DEFAULT):
        rates, shares = original(players, positions, teams, params)
        if mode == "default":
            return rates, shares
        f = fractions(players, positions, teams)
        out = {pos: dict(v) for pos, v in shares.items()}
        for pos, v in out.items():
            for stat in v:
                frac = f.get((pos, stat), 1.0)
                if mode == "zero_aware" or frac < OFF_ROLE:
                    v[stat] *= frac
        return rates, out
    return priors


async def run(league_id):
    async with get_worker_db() as db:
        leagues = (await db.scalars(select(SleeperLeague).where(SleeperLeague.platform == "sleeper"))).all()
        league = next(lg for lg in leagues if league_id in (None, lg.league_id))
        history = await engine.load_history(db, [2024, 2025, 2026], datetime.now(timezone.utc))
    weights_by_stat = {CORE[k]: w for k, w in offensive_weights(league.scoring_settings).items() if k in CORE}
    slates = week_slates(history)
    seasons = {s: [k for k in slates if k[0] == s] for s in (2025, 2026)}
    out = {}
    for mode in ("default", "zero_aware", "off_role"):
        engine.league_priors = variant(mode)
        out[mode] = {str(s): evaluate(history, slates, weights_by_stat, engine.DEFAULT, keys) for s, keys in seasons.items()}
    engine.league_priors = original
    p, s, t = (engine.league_priors(
        {k: v for k, v in history.players.items()}, history.positions,
        history.teams, engine.DEFAULT)[1], None, fractions(history.players, history.positions, history.teams))
    out["share_priors_now"] = {pos: {st: round(v, 4) for st, v in d.items()} for pos, d in p.items()}
    out["positive_fraction_now"] = {f"{pos}:{st}": round(v, 3) for (pos, st), v in sorted(t.items())}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league")
    print(json.dumps(asyncio.run(run(ap.parse_args().league)), indent=1))


if __name__ == "__main__":
    main()
