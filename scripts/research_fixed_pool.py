"""Re-score projection-engine variants on a variant-independent pool.

tune_projection_engine.evaluate picks each variant's pool by that variant's
own projection, so variants are graded on different players: a variant whose
projections spread out pulls its own busts into "top-N by projection". The
promotion gate (projection_engine_prospective.starter_pool) instead uses
top-N by Sleeper's projection or by actual. This grades every variant on that
gate pool: Sleeper's public weekly projections, one league's scoring.
Run in the worker environment: python -m scripts.research_fixed_pool [--league ID]
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
from collections import defaultdict
from datetime import datetime, timezone

import httpx
import numpy as np
from sqlalchemy import select

import src.services.projection_engine as engine
from src.db.client import get_worker_db
from src.models.sleeper import SleeperLeague
from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.player_identity import resolve_platform_players
from scripts.diagnose_projection_engine import sleeper_week
from scripts.research_role_prior import role_shares
from scripts.research_share_priors import variant
from scripts.tune_projection_engine import POOL, week_slates


def bootstrap(diffs_by_week, n=2000, seed=7):
    weeks = sorted(diffs_by_week)
    rng = np.random.default_rng(seed)
    stats = []
    for _ in range(n):
        pick = rng.choice(len(weeks), len(weeks))
        d = np.concatenate([diffs_by_week[weeks[i]] for i in pick])
        stats.append(d.mean())
    return [round(float(np.quantile(stats, 0.025)), 3), round(float(np.quantile(stats, 0.975)), 3)]


async def run(league_id, blend_only=False):
    async with get_worker_db() as db:
        leagues = (await db.scalars(select(SleeperLeague).where(SleeperLeague.platform == "sleeper"))).all()
        league = next(lg for lg in leagues if league_id in (None, lg.league_id))
        history = await engine.load_history(db, [2024, 2025, 2026], datetime.now(timezone.utc))
        slates = week_slates(history)
        keys = sorted(k for k in slates if k[0] in (2025, 2026))
        async with httpx.AsyncClient(timeout=60) as c:
            sleeper = {k: await sleeper_week(c, *k) for k in keys}
        ids = await resolve_platform_players(db, "sleeper", sorted({i for v in sleeper.values() for i in v}))
    sw = offensive_weights(league.scoring_settings)
    wbs = {CORE[k]: w for k, w in sw.items() if k in CORE}
    sleeper_points = {k: {ids[i].id: sum(float(s.get(a, 0)) * w for a, w in sw.items()) for i, s in v.items() if ids.get(i)}
                      for k, v in sleeper.items()}

    # Fixed pool per week-position: Sleeper top-N or actual top-N among players who played and Sleeper projected.
    pools = {}
    for k in keys:
        _, _, actual = slates[k]
        groups = defaultdict(list)
        for pid, played in actual.items():
            pos = history.positions.get(pid)
            if pos in POOL and pid in sleeper_points[k]:
                groups[pos].append((pid, sleeper_points[k][pid], engine.score(played.stats, wbs)))
        chosen = set()
        for pos, members in groups.items():
            n = POOL[pos]
            chosen |= {m[0] for m in sorted(members, key=lambda m: -m[1])[:n]}
            chosen |= {m[0] for m in sorted(members, key=lambda m: -m[2])[:n]}
        pools[k] = chosen

    def grade(label):
        rows = []  # (key, pos, engine, sleeper, actual)
        for k in keys:
            cutoff, targets, actual = slates[k]
            proj = engine.compute(history, targets, cutoff, engine.DEFAULT)
            for pid in pools[k]:
                p, played = proj.get(pid), actual[pid]
                if p is None or p.game_id != played.game_id:
                    continue
                rows.append((k, p.position, engine.score(p.stats, wbs), sleeper_points[k][pid], engine.score(played.stats, wbs)))
        return rows

    def summarize(rows, base=None):
        out = {}
        for season in (2025, 2026):
            r = [x for x in rows if x[0][0] == season]
            e = np.array([abs(x[2] - x[4]) for x in r]); s = np.array([abs(x[3] - x[4]) for x in r])
            by_week = defaultdict(list)
            for x in r:
                by_week[x[0]].append(abs(x[2] - x[4]) - abs(x[3] - x[4]))
            out[str(season)] = {"n": len(r), "engine": round(float(e.mean()), 4), "sleeper": round(float(s.mean()), 4),
                                "vs_sleeper_ci": bootstrap({k: np.array(v) for k, v in by_week.items()}),
                                "bias": round(float(np.mean([x[2] - x[4] for x in r])), 3),
                                "by_position": {p: round(float(np.mean([abs(x[2] - x[4]) for x in r if x[1] == p])), 3) for p in POOL}}
            if base is not None:
                bmap = {(x[0], x[1], x[4], x[3]): x[2] for x in base}
                by_w = defaultdict(list)
                for x in r:
                    b = bmap.get((x[0], x[1], x[4], x[3]))
                    if b is not None:
                        by_w[x[0]].append(abs(x[2] - x[4]) - abs(b - x[4]))
                out[str(season)]["vs_default_ci"] = bootstrap({k: np.array(v) for k, v in by_w.items()})
        return out

    base = grade("default")
    out = {"default": summarize(base)}
    if blend_only:
        # Engine/Sleeper blend weight per position, chosen on 2025, scored on 2026.
        grid = np.round(np.arange(0, 1.01, 0.1), 2)
        def mae(rows, w):
            return float(np.mean([abs(w * x[2] + (1 - w) * x[3] - x[4]) for x in rows])) if rows else None
        blend = {}
        for pos in POOL:
            r25 = [x for x in base if x[0][0] == 2025 and x[1] == pos]
            r26 = [x for x in base if x[0][0] == 2026 and x[1] == pos]
            w = min(grid, key=lambda g: mae(r25, g))
            blend[pos] = {"engine_weight_2025": float(w), "2026_blend": round(mae(r26, w), 3),
                          "2026_engine": round(mae(r26, 1.0), 3), "2026_sleeper": round(mae(r26, 0.0), 3),
                          "2026_half": round(mae(r26, 0.5), 3), "2025_by_weight": {str(g): round(mae(r25, g), 3) for g in grid}}
        chosen = {pos: v["engine_weight_2025"] for pos, v in blend.items()}
        by_week = defaultdict(list)
        for x in base:
            if x[0][0] == 2026:
                w = chosen[x[1]]
                by_week[x[0]].append(abs(w * x[2] + (1 - w) * x[3] - x[4]) - abs(x[2] - x[4]))
        out["blend"] = {"by_position": blend, "2026_blend_vs_engine_ci": bootstrap({k: np.array(v) for k, v in by_week.items()}),
                        "2026_blend_mae": round(float(np.mean(np.concatenate([np.array(v) for v in by_week.values()]))) + out["default"]["2026"]["engine"], 4)}
        return out
    variants = {"off_role": (None, "off_role")}
    for role_games, k_position in itertools.product((8, 16), (1.0, 3.0, 6.0)):
        variants[f"role{role_games}_k{k_position}"] = ((role_games, k_position), None)
        variants[f"role{role_games}_k{k_position}_offrole"] = ((role_games, k_position), "off_role")
    for name, (role, prior) in variants.items():
        engine.player_shares = role_shares(*role) if role else role_shares.__globals__["original_shares"]
        engine.league_priors = variant(prior) if prior else variant("default")
        out[name] = summarize(grade(name), base)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league")
    ap.add_argument("--blend", action="store_true", help="engine/Sleeper blend only")
    a = ap.parse_args()
    print(json.dumps(asyncio.run(run(a.league, a.blend)), indent=1))


if __name__ == "__main__":
    main()
