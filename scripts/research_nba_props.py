"""Fit and test the NBA prop engine (src/services/nba_prop_engine.py) on 2025-26.

Run inside the evaluation container:
    docker cp scripts/research_nba_props.py fantasy-edge-evaluation-1:/tmp/nba.py
    docker exec -w /app -e PYTHONPATH=/app fantasy-edge-evaluation-1 python /tmp/nba.py [--write]

Walk-forward: every player-game is projected from strictly earlier games.
Tuning (half-life, shrinkage) and coefficients use regular-season games
before 2026-02-01; the test is 2026-02-01 to the end of the regular season.
Baselines: last-10 played mean and season-to-date mean. Probabilities are
checked at a book-like line (nearest .5 to the last-10 mean). --write refits
coefficients and quantiles on the whole season and writes
config/nba_prop_model.json with the test metrics.
"""

import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from scipy.optimize import minimize
from sqlalchemy import select

from src.db.client import get_worker_db
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player
from src.services import nba_prop_engine as E
from src.services.nba_context import player_teams

SPLIT = datetime(2026, 2, 1, tzinfo=timezone.utc)
SEASON = 2026


async def load():
    async with get_worker_db() as db:
        context = await player_teams(db)
        games = {str(g.id): g for g in (await db.scalars(select(Game).where(
            Game.sport == "nba", Game.status == "final", Game.season == SEASON, Game.game_time.is_not(None)))).all()}
        rows = (await db.execute(select(PlayerGameStat.player_id, PlayerGameStat.game_id, PlayerGameStat.stat_type,
                                        PlayerGameStat.value).where(PlayerGameStat.game_id.in_([g.id for g in games.values()])))).all()
        groups = {str(p.id): E.GROUP.get(p.position) for p in (await db.scalars(select(Player).where(Player.sport == "nba"))).all()}
    stats = defaultdict(dict)
    for pid, gid, stat, value in rows:
        stats[(str(pid), str(gid))][stat] = float(value)
    return context, games, stats, groups


def walk(context, games, stats, groups, half_life, shrink):
    """[(row dict)] for every REG/POST player-game with a base projection."""
    by_game = defaultdict(list)
    for (pid, gid), s in stats.items():
        by_game[gid].append((pid, s))
    history, league, out = defaultdict(list), E.League(), []
    for gid in sorted(by_game, key=lambda g: games[g].game_time):
        g, ctx = games[gid], context.get(gid)
        if ctx is None:
            continue
        home, away = str(g.home_team_id), str(g.away_team_id)
        entries = []
        for pid, s in by_game[gid]:
            team, group = ctx["players"].get(pid), groups.get(pid)
            if team not in (home, away) or group is None or "minutes" not in s:
                continue
            opponent = away if team == home else home
            spread = None if ctx["home_spread"] is None else (ctx["home_spread"] if team == home else -ctx["home_spread"])
            played = E.Played(gid, g.game_time, g.season, team, opponent, pid in ctx["starters"], s, ctx["total"], spread)
            if s["minutes"] > 0 and g.game_type in ("REG", "POST"):
                base = E.base_projection(history[pid], group, league, g.season, half_life=half_life, shrink=shrink)
                if base is not None and base["games"] >= 3:
                    recent = [p.stats for p in history[pid] if p.stats.get("minutes", 0) > 0][-10:]
                    season_games = [p.stats for p in history[pid] if p.stats.get("minutes", 0) > 0 and p.season == g.season]
                    out.append({"time": g.game_time, "type": g.game_type, "pid": pid, "group": group, "base": base,
                                "x": {st: E.features(ctx["total"], spread, league.opponent_factor(opponent, group, st)) for st in E.BASE},
                                "actual": {st: s.get(st, 0.0) for st in E.STATS},
                                "l10": {st: float(np.mean([r.get(st, 0.0) for r in recent])) for st in E.STATS},
                                "season": {st: float(np.mean([r.get(st, 0.0) for r in season_games])) if season_games else None for st in E.STATS}})
            entries.append((pid, played, group, opponent))
        # Only after the whole game is projected: no same-game information.
        for pid, played, group, opponent in entries:
            history[pid].append(played)
            if played.stats["minutes"] > 0:
                league.add(group, opponent, gid, played.stats)
    return out


def poisson_deviance(y, mu):
    mu = np.maximum(mu, 1e-9)
    return float(np.mean(2 * (np.where(y > 0, y * np.log(np.maximum(y, 1e-9) / mu), 0) - (y - mu))))


def fit(rows):
    coefficients = {}
    for st in E.BASE:
        X = np.array([r["x"][st] for r in rows])
        y = np.array([r["actual"][st] for r in rows])
        o = np.log(np.maximum([r["base"][st] for r in rows], 1e-6))

        def loss(b):
            eta = o + X @ b
            return float(np.mean(np.exp(eta) - y * eta))
        coefficients[st] = [round(float(v), 5) for v in minimize(loss, np.zeros(4), method="BFGS").x]
    return coefficients


def means(rows, coefficients):
    for r in rows:
        m = {st: r["base"][st] * float(np.exp(np.array(coefficients[st]) @ r["x"][st])) for st in E.BASE}
        for combo, parts in E.COMBOS.items():
            m[combo] = sum(m[p] for p in parts)
        r["mean"] = m


def distribution(rows):
    out = {}
    for st in E.STATS:
        mean = np.array([r["mean"][st] for r in rows])
        ratio = np.array([r["actual"][st] for r in rows]) / np.maximum(mean, 1e-6)
        edges = [float(np.quantile(mean, 1 / 3)), float(np.quantile(mean, 2 / 3))]
        bucket = np.where(mean < edges[0], 0, np.where(mean < edges[1], 1, 2))
        out[st] = {"edges": [round(e, 4) for e in edges],
                   "quantiles": [[round(float(v), 4) for v in np.quantile(ratio[bucket == b], np.linspace(0, 1, 101))] for b in range(3)]}
    return out


def evaluate(rows, artifact):
    report = {}
    for st in E.STATS:
        y = np.array([r["actual"][st] for r in rows])
        model = np.array([r["mean"][st] for r in rows])
        l10 = np.array([r["l10"][st] for r in rows])
        season = np.array([r["season"][st] if r["season"][st] is not None else r["l10"][st] for r in rows])
        lines = np.floor(l10) + 0.5
        p = np.array([E.over_probability(st, m, ln, artifact) or 0.0 for m, ln in zip(model, lines)])
        hit = (y > lines).astype(float)
        # Paired bootstrap of MAE(model) - MAE(l10), resampling player-games.
        rng = np.random.default_rng(7)
        d = np.abs(model - y) - np.abs(l10 - y)
        boot = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(1000)]
        report[st] = {"n": len(y), "mae_model": round(float(np.abs(model - y).mean()), 3),
                      "mae_l10": round(float(np.abs(l10 - y).mean()), 3), "mae_season": round(float(np.abs(season - y).mean()), 3),
                      "mae_diff_vs_l10_ci": [round(float(np.quantile(boot, q)), 3) for q in (0.025, 0.975)],
                      "brier_model": round(float(((p - hit) ** 2).mean()), 4),
                      "brier_base_rate": round(float(((hit.mean() - hit) ** 2).mean()), 4), "mean_p": round(float(p.mean()), 3), "observed": round(float(hit.mean()), 3),
                      "bias": round(float((model - y).mean()), 3), "calibration": [(lo, int(m.sum()), round(float(p[m].mean()), 3), round(float(hit[m].mean()), 3)) for lo in (0, .2, .4, .6, .8) if (m := (p >= lo) & (p < lo + .2)).any()]}
    return report


async def main():
    context, games, stats, groups = await load()
    grid = []
    for half_life in (8.0, 10.0, 14.0):
        for shrink in (15.0, 30.0, 60.0):
            rows = [r for r in walk(context, games, stats, groups, half_life, shrink) if r["type"] == "REG" and r["time"] < SPLIT]
            dev = np.mean([poisson_deviance(np.array([r["actual"][st] for r in rows]), np.array([r["base"][st] for r in rows])) for st in E.BASE])
            grid.append((dev, half_life, shrink))
            print(f"half_life {half_life} shrink {shrink}: train base deviance {dev:.4f} rows {len(rows)}", flush=True)
    _, half_life, shrink = min(grid)
    rows = walk(context, games, stats, groups, half_life, shrink)
    train = [r for r in rows if r["type"] == "REG" and r["time"] < SPLIT]
    test = [r for r in rows if r["type"] == "REG" and r["time"] >= SPLIT]
    coefficients = fit(train)
    means(train, coefficients)
    means(test, coefficients)
    held = {"distribution": distribution(train)}
    report = evaluate(test, held)
    print(json.dumps({"half_life": half_life, "shrink": shrink, "coefficients": coefficients}, indent=1))
    for st, r in report.items():
        print(st, r)
    if "--write" in sys.argv:
        everything = [r for r in rows if r["type"] == "REG"]
        final = fit(everything)
        means(everything, final)
        artifact = {"version": 1, "fitted_on": "2025-26 regular season, walk-forward", "half_life": half_life,
                    "shrink_minutes": shrink, "coefficients": final, "features": ["intercept", "log(total/229)", "|spread|", "log(opponent factor)"],
                    "distribution": distribution(everything), "test": {"split": SPLIT.isoformat(), "coefficients": coefficients, "report": report},
                    "generated_at": datetime.now(timezone.utc).isoformat()}
        with open("/tmp/nba_prop_model.json", "w") as f:
            json.dump(artifact, f, indent=1)
        print("wrote /tmp/nba_prop_model.json")


asyncio.run(main())
