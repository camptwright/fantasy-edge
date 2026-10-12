"""Fit and validate config/fantasy_outcome_model.json (src/services/fantasy_outcomes.py).

Run in the worker environment (needs the DB and the raw archive):
    python -m scripts.fit_fantasy_outcomes [--write]

1. Blend weights (E5): paired retrospective rows from
   scripts.backtest_projection_engine (engine v1 vs frozen Sleeper, both
   graded on platform final points). Per position, the squared-error-optimal
   weight on the engine, clipped to [0, 1] and shrunk toward 0 (Sleeper) by
   weeks / (weeks + SHRINK_WEEKS).
2. Dispersion: frozen Sleeper pre-kickoff projections (all positions) graded
   on platform final points. sd(mean) = a + b * mean from a least-squares fit
   of |residual| * sqrt(pi/2) on the projection; standardized residual
   quantiles kept as the marginal shape.
3. Correlations: nflverse 2025 regular-season player-games, half-PPR points,
   residual against the player's own trailing mean (>= 3 prior games, mean
   >= 4), standardized by position; Pearson by relation (same team /
   opponents) and position pair. 2025 only, so 2026 checks stay out of sample.
4. Validation, leave-one-week-out over graded 2026 weeks: blend MAE vs
   Sleeper; p10/p90 coverage; head-to-head matchup win probability (Brier
   and log loss) for correlated vs independent simulation vs a coin flip.

Nothing is promoted. --write saves the model fitted on all weeks with its
validation summary; without it the script only reports.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy import or_, select

from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.facts import Game, PlayerGameStat, PlayerSnapCount
from src.models.identity import Player, Team
from src.models.sleeper import SleeperLeagueSnapshot
from src.services import fantasy_outcomes as fo
from src.services.fantasy_weekly_evidence import grade
from src.services.projection_engine_prospective import latest_sleeper_catalog

SHRINK_WEEKS = 4
Z_PROBS = [0.0, 0.005, 0.01, 0.025, 0.05] + [round(x, 2) for x in np.arange(0.1, 0.91, 0.05)] + [0.95, 0.975, 0.99, 0.995, 1.0]
HALF_PPR = {"receptions": 0.5, "receiving_yards": 0.1, "receiving_touchdowns": 6, "rushing_yards": 0.1,
            "rushing_touchdowns": 6, "passing_yards": 0.04, "passing_touchdowns": 4,
            "passing_interceptions": -2, "fumbles_lost": -2}
ALIAS = {"LA": "LAR", "WSH": "WAS", "JAC": "JAX"}


def fit_blend(rows: list[dict]) -> dict:
    out = {}
    for pos in fo.OFFENSE:
        r = [x for x in rows if x["position"] == pos]
        if len(r) < 30:
            out[pos] = 0.0
            continue
        e = np.array([x["engine"] for x in r])
        s = np.array([x["sleeper"] for x in r])
        a = np.array([x["actual"] for x in r])
        d = e - s
        w = float(np.clip(np.dot(d, a - s) / np.dot(d, d), 0, 1)) if np.dot(d, d) > 0 else 0.0
        weeks = len({x["week"] for x in r})
        out[pos] = round(w * weeks / (weeks + SHRINK_WEEKS), 3)
    return out


def fit_dispersion(rows: list[dict]) -> dict:
    """rows: position, mean, actual."""
    def one(r):
        m = np.array([x["mean"] for x in r])
        res = np.array([x["actual"] for x in r]) - m
        target = np.abs(res) * math.sqrt(math.pi / 2)
        design = np.column_stack([np.ones(len(m)), np.clip(m, 0, None)])
        (a, b), *_ = np.linalg.lstsq(design, target, rcond=None)
        b = max(float(b), 0.0)
        a = float(np.mean(target - b * np.clip(m, 0, None)))
        sd = np.maximum(1.0, a + b * np.clip(m, 0, None))
        z = res / sd
        return {"a": round(a, 4), "b": round(b, 4), "sd_min": 1.0, "n": len(r),
                "z_probs": Z_PROBS, "z_values": [round(float(v), 4) for v in np.quantile(z, Z_PROBS)]}
    out = {pos: one([x for x in rows if x["position"] == pos])
           for pos in ("QB", "RB", "WR", "TE", "K", "DEF") if sum(x["position"] == pos for x in rows) >= 40}
    out["default"] = one(rows)
    return out


async def correlations(db) -> dict:
    games = {g.id: g for g in (await db.scalars(select(Game).where(
        Game.sport == "nfl", Game.season == 2025, Game.status == "final",
        or_(Game.game_type.is_(None), Game.game_type == "REG")))).all()}
    team_of = {(p, g): t for p, g, t in (await db.execute(select(
        PlayerSnapCount.player_id, PlayerSnapCount.game_id, PlayerSnapCount.team_id)
        .where(PlayerSnapCount.game_id.in_(list(games))))).all()}
    points: dict[tuple, float] = defaultdict(float)
    for pid, gid, stat, value in (await db.execute(select(
            PlayerGameStat.player_id, PlayerGameStat.game_id, PlayerGameStat.stat_type, PlayerGameStat.value)
            .where(PlayerGameStat.game_id.in_(list(games)), PlayerGameStat.stat_type.in_(list(HALF_PPR))))).all():
        points[(pid, gid)] += value * HALF_PPR[stat]
    position = dict((await db.execute(select(Player.id, Player.position).where(
        Player.id.in_({p for p, _ in team_of})))).all())
    by_player = defaultdict(list)
    for (pid, gid), team in team_of.items():
        if position.get(pid) in fo.OFFENSE:
            by_player[pid].append((games[gid].game_time, gid, team, points.get((pid, gid), 0.0)))
    residuals = defaultdict(list)  # game -> (player, team, position, residual)
    for pid, rows in by_player.items():
        rows.sort(key=lambda r: r[0])
        for i, (_, gid, team, pts) in enumerate(rows):
            prior = [r[3] for r in rows[max(0, i - 6):i]]
            if len(prior) >= 3 and np.mean(prior) >= 4:
                residuals[gid].append((pid, team, position[pid], pts - float(np.mean(prior))))
    scale = {pos: float(np.std([r[3] for g in residuals.values() for r in g if r[2] == pos])) for pos in fo.OFFENSE}
    sums = defaultdict(lambda: [0.0, 0.0, 0.0, 0])
    for gid, rows in residuals.items():
        game = games[gid]
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                same = a[1] == b[1]
                if not same and {a[1], b[1]} != {game.home_team_id, game.away_team_id}:
                    continue
                first, second = sorted((a[2], b[2]))
                za, zb = a[3] / scale[a[2]], b[3] / scale[b[2]]
                s = sums[f"{'same' if same else 'opp'}:{first}-{second}"]
                s[0] += za * zb
                s[1] += za * za
                s[2] += zb * zb
                s[3] += 1
    out = {}
    for key, (xy, xx, yy, n) in sorted(sums.items()):
        if n >= 100:
            rho = xy / math.sqrt(xx * yy)
            se = (1 - rho ** 2) / math.sqrt(n)
            out[key] = {"rho": round(rho, 4), "n": n, "se": round(se, 4)}
    return out


async def collect(db):
    from scripts.backtest_projection_engine import run as backtest
    report = await backtest(2026)
    paired = json.loads(Path(report["archive"]).read_text())["rows"]
    engine_by = {(r["league_id"], r["week"], r["player_id"]): r["engine"] for r in paired}
    root = Path(get_settings().raw_archive_dir) / "fantasy-prospective" / "provider-weekly"
    records = [json.loads(p.read_text()) for p in sorted(root.glob("*.json"))]
    records = [r for r in records if not r["league_id"].startswith("espn:")
               and r.get("prediction", {}).get("source") == "sleeper"]
    games = {g.id: g for g in (await db.scalars(select(Game).where(
        Game.id.in_({uuid.UUID(r["game_id"]) for r in records})))).all()}
    snapshots, graded = {}, []
    for r in records:
        key = (r["league_id"], r["week"])
        if key not in snapshots:
            snapshots[key] = await db.get(SleeperLeagueSnapshot, (r["league_id"], r["week"], "matchups"))
        g = grade(r, games.get(uuid.UUID(r["game_id"])), snapshots[key])
        if g["status"] == "graded_platform_total":
            graded.append({"league_id": r["league_id"], "week": r["week"], "player_id": r["player_id"],
                           "position": r["position"], "game_id": r["game_id"], "mean": r["prediction"]["points"],
                           "sleeper": r["prediction"]["points"], "actual": g["actual"],
                           "engine": engine_by.get((r["league_id"], r["week"], r["player_id"]))})
    catalog, _ = await latest_sleeper_catalog(db)
    teams = (await db.scalars(select(Team).where(Team.sport == "nfl"))).all()
    team_by_abbr = {ALIAS.get(t.nflverse_abbr, t.nflverse_abbr): t.id for t in teams if t.nflverse_abbr}
    return paired, graded, snapshots, games, catalog, team_by_abbr


def matchups(graded, snapshots, games, catalog, team_by_abbr):
    by = {(r["league_id"], r["week"], r["player_id"]): r for r in graded}
    out = []
    for (league, week), snap in snapshots.items():
        if snap is None or not isinstance(snap.payload, list):
            continue
        groups = defaultdict(list)
        for row in snap.payload:
            if row.get("matchup_id") is not None:
                groups[row["matchup_id"]].append(row)
        for rows in groups.values():
            if len(rows) != 2 or rows[0].get("points") is None or rows[1].get("points") is None:
                continue
            sides = []
            for row in rows:
                players = []
                for pid in map(str, row.get("starters") or []):
                    g = by.get((league, week, pid))
                    if g is None:
                        break
                    game = games[uuid.UUID(g["game_id"])]
                    abbr = (catalog.get(pid) or {}).get("team")
                    team = team_by_abbr.get(ALIAS.get(abbr, abbr))
                    opponent = (game.away_team_id if team == game.home_team_id else game.home_team_id
                                if team == game.away_team_id else None)
                    players.append({**g, "team": team, "opponent": opponent})
                else:
                    sides.append(players)
                    continue
                break
            if len(sides) == 2 and rows[0]["points"] != rows[1]["points"]:
                out.append({"league_id": league, "week": week, "a": sides[0], "b": sides[1],
                            "a_won": rows[0]["points"] > rows[1]["points"]})
    return out


def with_means(players, blend):
    out = []
    for p in players:
        mean, _ = fo.blend_mean(p["position"], p["sleeper"], p.get("engine"), {"blend_weights": blend})
        out.append({**p, "mean": mean})
    return out


def validate(paired, graded, games_list, corr):
    weeks = sorted({r["week"] for r in graded})
    blend_rows, coverage, results = [], [], []
    for held in weeks:
        blend = fit_blend([r for r in paired if r["week"] != held])
        dispersion = fit_dispersion([r for r in graded if r["week"] != held])
        model = {"blend_weights": blend, "dispersion": dispersion, "correlations": corr}
        for r in paired:
            if r["week"] == held:
                mean, _ = fo.blend_mean(r["position"], r["sleeper"], r["engine"], model)
                blend_rows.append((abs(mean - r["actual"]), abs(r["sleeper"] - r["actual"]), held))
        for r in graded:
            if r["week"] == held:
                sd, probs, values = fo.spread(r["position"], r["mean"], model)
                p10 = r["mean"] + sd * np.interp(0.1, probs, values)
                p90 = r["mean"] + sd * np.interp(0.9, probs, values)
                coverage.append((r["actual"] < p10, r["actual"] > p90))
        for m in (x for x in games_list if x["week"] == held):
            a, b = with_means(m["a"], blend), with_means(m["b"], blend)
            players = [{**p, "player_id": f"a{i}"} for i, p in enumerate(a)] + [{**p, "player_id": f"b{i}"} for i, p in enumerate(b)]
            row = {"week": held, "a_won": m["a_won"]}
            for name, correlated in (("correlated", True), ("independent", False)):
                s = fo.simulate(players, model, draws=20000, correlated=correlated)
                row[name] = fo.matchup([p["player_id"] for p in players[:len(a)]],
                                       [p["player_id"] for p in players[len(a):]], s)["win_probability"]
            results.append(row)

    def scores(key):
        p = np.clip(np.array([r[key] if key != "coin" else 0.5 for r in results]), 1e-3, 1 - 1e-3)
        y = np.array([r["a_won"] for r in results], dtype=float)
        return {"brier": round(float(np.mean((p - y) ** 2)), 4),
                "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4)}
    b = np.array(blend_rows) if blend_rows else np.zeros((0, 3))
    return {"weeks": weeks,
            "blend_vs_sleeper_mae": {"rows": len(b), "blend": round(float(b[:, 0].mean()), 3) if len(b) else None,
                                     "sleeper": round(float(b[:, 1].mean()), 3) if len(b) else None},
            "interval_coverage": {"rows": len(coverage),
                                  "below_p10": round(float(np.mean([c[0] for c in coverage])), 3) if coverage else None,
                                  "above_p90": round(float(np.mean([c[1] for c in coverage])), 3) if coverage else None},
            "matchups": {"n": len(results), **{k: scores(k) for k in ("correlated", "independent", "coin")}},
            "method": "leave-one-week-out; correlations fitted on 2025 only"}


async def main(write: bool) -> dict:
    async with get_worker_db() as db:
        corr = await correlations(db)
        paired, graded, snapshots, games, catalog, team_by_abbr = await collect(db)
    games_list = matchups(graded, snapshots, games, catalog, team_by_abbr)
    validation = validate(paired, graded, games_list, corr)
    candidate = fit_blend(paired)
    mae = validation["blend_vs_sleeper_mae"]
    # Applied only when the leave-one-week-out blend beat the provider; the
    # candidate is still graded prospectively (projection_engine_prospective).
    improved = mae["blend"] is not None and mae["blend"] < mae["sleeper"]
    model = {"recipe": "fantasy_outcomes_v1", "fitted_at": datetime.now(timezone.utc).isoformat(),
             "blend_weights": candidate if improved else dict.fromkeys(candidate, 0.0),
             "candidate_blend_weights": candidate,
             "blend_status": "applied_out_of_sample_improvement" if improved else "provider_only_blend_not_better_out_of_sample",
             "blend_shrink_weeks": SHRINK_WEEKS,
             "dispersion": fit_dispersion(graded), "correlations": corr,
             "fit_data": {"paired_rows": len(paired), "graded_rows": len(graded),
                          "paired_weeks": sorted({r["week"] for r in paired}),
                          "graded_weeks": sorted({r["week"] for r in graded}),
                          "correlation_source": "nflverse 2025 REG half-PPR residuals"},
             "validation": validation, "serving_promoted": False}
    if write:
        fo.MODEL_PATH.write_text(json.dumps(model, indent=1) + "\n")
    return model


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()
    result = asyncio.run(main(args.write and not args.out))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: result[k] for k in ("blend_weights", "candidate_blend_weights", "blend_status",
                                             "validation", "fit_data")}, indent=1))
