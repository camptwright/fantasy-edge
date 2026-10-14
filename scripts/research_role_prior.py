"""Role-anchored share priors for projection engine v1 (walk-forward, tune harness).

diagnose_projection_engine: on the FantasyPros pool the engine under-projects
volume (RB carries -1.1, WR targets -0.8, TE targets -1.2 a game; Sleeper
-0.3/-0.3/-0.6). player_shares shrinks a recency-weighted share (half-life 2
games, so five games weigh ~2.8) toward one position-wide prior with 1.5
games of weight: a WR1 at 28% is pulled to ~23% by a 13% typical share.

Variant `role`: the prior is the player's own share over his last ROLE_GAMES
games for the team (unweighted), itself shrunk toward the position prior
with `k_position` games; the recent EWMA then shrinks toward that role with
the engine's share_prior_games. Optional `off_role`: position priors times
the position's fraction of games with a positive share where that is < 0.5.
Run in the worker environment: python -m scripts.research_role_prior [--league ID]
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select

import src.services.projection_engine as engine
from src.db.client import get_worker_db
from src.models.sleeper import SleeperLeague
from src.services.fantasy_decision_models import CORE, offensive_weights
from scripts.research_share_priors import variant
from scripts.tune_projection_engine import evaluate, week_slates

original_shares = engine.player_shares
original_priors = engine.league_priors


def role_shares(role_games, k_position):
    def shares(position, games, teams, share_priors, params=engine.DEFAULT):
        long = games[-role_games:]
        recent = games[-engine.PLAYER_LOOKBACK:]
        out = {}
        for stat, team_stat in engine.SHARE_STATS:
            if stat == "passing_attempts" and position != "QB":
                out[stat] = 0.0
                continue

            def values(gs):
                v = []
                for g in gs:
                    total = getattr(teams[(g.game_id, g.team_id)], team_stat)
                    if total > 0:
                        v.append(g.stats.get(stat, 0.0) / total)
                return v
            lv, rv = values(long), values(recent)
            base = share_priors[position][stat]
            role = (sum(lv) + k_position * base) / (len(lv) + k_position)
            out[stat] = engine.shrunk_share(rv, role, params)
        return out
    return shares


async def run(league_id):
    async with get_worker_db() as db:
        leagues = (await db.scalars(select(SleeperLeague).where(SleeperLeague.platform == "sleeper"))).all()
        league = next(lg for lg in leagues if league_id in (None, lg.league_id))
        history = await engine.load_history(db, [2024, 2025, 2026], datetime.now(timezone.utc))
    wbs = {CORE[k]: w for k, w in offensive_weights(league.scoring_settings).items() if k in CORE}
    slates = week_slates(history)
    seasons = {s: [k for k in slates if k[0] == s] for s in (2025, 2026)}

    def ev(label):
        r = {str(s): evaluate(history, slates, wbs, engine.DEFAULT, keys) for s, keys in seasons.items()}
        return {s: {"pool_mae": round(v["pool_mae"], 4), "all_mae": round(v["all_mae"], 4),
                    "pool_bias": round(v["pool_bias"], 3), "by_position": v["by_position_pool_mae"]} for s, v in r.items()}
    out = {"default": ev("default")}
    for role_games, k_position, off in itertools.product((8, 16), (1.0, 3.0), (False, True)):
        engine.player_shares = role_shares(role_games, k_position)
        engine.league_priors = variant("off_role") if off else original_priors
        out[f"role{role_games}_k{k_position}_{'offrole' if off else 'plain'}"] = ev("")
    engine.player_shares, engine.league_priors = original_shares, original_priors
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league")
    print(json.dumps(asyncio.run(run(ap.parse_args().league)), indent=1))


if __name__ == "__main__":
    main()
