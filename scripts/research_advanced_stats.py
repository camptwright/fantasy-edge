"""Do advanced usage stats improve NFL fantasy projections? Research only.

Question: beyond the box-score volume the engine already uses (targets,
carries, attempts and their team shares), do snap share, a route proxy,
targets per route, air-yard share, aDOT, red-zone and goal-line shares and
nflverse expected fantasy points (xFP) carry information about next week's
fantasy points, and does that information close the gap to Sleeper?

Design (no database; nflverse + Sleeper's historical projections):
- Graded rows: every player-week in 2023-2025 W1-18 that has an engine
  projection, a Sleeper projection and a stat line, built exactly as in
  scripts/research_holdout.py. 2022 is history only: it is the sealed season
  for the next registered engine test and is never graded here.
- Features: trailing, strictly before the graded game's kickoff, over the
  player's last PLAYER_GAMES games (exponential weight, half-life HALF_LIFE),
  plus last-game values for role changes.
- Models: gradient-boosted residual corrections (absolute-error loss)
  trained leave-one-season-out; each season's predictions come from a model
  fit on the other two dev seasons only. Same model, two feature sets: box
  score only vs box score + advanced. The difference between them is the
  value of the advanced stats.
- Grading: the symmetric starter pool (top 12/24/30/12 by Sleeper OR by the
  candidate), paired absolute error, week-cluster bootstrap CI (4000 draws).

Known limits: nflverse's xFP is a play-level expectation model fit by
nflverse on historical seasons that may overlap the dev seasons; the route
proxy counts every on-field player on a dropback (overstates RB routes);
leave-one-season-out lets 2025 inform the 2023 model, so this measures
whether the information exists, not a deployable walk-forward score.

    .venv/bin/python -m scripts.research_advanced_stats --scoring warriors_scoring.json
"""

from __future__ import annotations

import argparse
import json
import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np

from scripts.research_holdout import GATE_POOL, nflverse_history, sleeper_to_gsis, sleeper_week
from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.projection_engine import DEFAULT, compute, score
from src.services.projection_engine_prospective import week_bootstrap_ci

DEV = (2023, 2024, 2025)
HISTORY = (2022, 2023, 2024, 2025)
PLAYER_GAMES, HALF_LIFE = 12, 3.0
POSITIONS = ("QB", "RB", "WR", "TE")
DRAWS, SEED = 4000, 0

BOX = ["fp", "targets", "carries", "pass_att", "tgt_share", "carry_share", "games"]
ADVANCED = ["xfp", "fp_minus_xfp", "snap_share", "route_share", "tprr", "air_share", "adot", "wopr",
            "rz_tgt_share", "rz_carry_share", "gl_carry_share", "snap_share_last", "route_share_last",
            "snap_trend", "xfp_last"]
# nflverse ff_opportunity expected components -> league scoring keys
XFP_COMPONENTS = {"receptions_exp": "rec", "rec_yards_gained_exp": "rec_yd", "rec_touchdown_exp": "rec_td",
                  "rush_yards_gained_exp": "rush_yd", "rush_touchdown_exp": "rush_td",
                  "pass_yards_gained_exp": "pass_yd", "pass_touchdown_exp": "pass_td",
                  "pass_interception_exp": "pass_int", "rec_two_point_conv_exp": "rec_2pt",
                  "rush_two_point_conv_exp": "rush_2pt", "pass_two_point_conv_exp": "pass_2pt"}


def graded_rows(history, scoring, crosswalk) -> list[dict]:
    """research_holdout.rows_for, keeping player and game ids."""
    sw = offensive_weights(scoring)
    internal = {CORE[k]: w for k, w in sw.items() if k in CORE}
    by_week = defaultdict(list)
    for g in history.games.values():
        by_week[(g.season, g.week)].append(g)
    rows = []
    for key in [(s, w) for s in DEV for w in range(1, 19)]:
        targets = []
        for g in by_week.get(key, []):
            home, away = history.teams.get((g.id, g.home_team_id)), history.teams.get((g.id, g.away_team_id))
            if home and away and home.implied_points is not None and away.implied_points is not None:
                targets.append((g, home.implied_points, away.implied_points, home.spread))
        if not targets:
            continue
        cutoff = min(g.game_time for g, *_ in targets)
        ids = {g.id for g, *_ in targets}
        actual = {p.player_id: p for p in history.players.values() if p.game_id in ids}
        sleeper = {crosswalk[k]: v for k, v in sleeper_week(*key).items() if k in crosswalk}
        for pid, proj in compute(history, targets, cutoff, DEFAULT).items():
            got, s = actual.get(pid), sleeper.get(pid)
            if got is None or got.game_id != proj.game_id or s is None:
                continue
            rows.append({"season": key[0], "week": key[1], "position": proj.position, "player_id": pid,
                         "game_id": got.game_id, "kickoff": got.kickoff, "team": got.team_id,
                         "engine": score(proj.stats, internal),
                         "sleeper": sum(float(s.get(k, 0) or 0) * w for k, w in sw.items()),
                         "actual": score(got.stats, internal)})
        print("rows", key, len(rows), flush=True)
    return rows


def player_games(history, scoring) -> dict[str, list[dict]]:
    """Per player, chronological per-game usage: box score plus advanced."""
    import nflreadpy as nfl
    import polars as pl
    sw = offensive_weights(scoring)
    internal = {CORE[k]: w for k, w in sw.items() if k in CORE}
    seasons = list(HISTORY)
    pbp = nfl.load_pbp(seasons).filter(pl.col("season_type") == "REG").filter(
        pl.col("play_type").is_in(["pass", "run"]) & (pl.col("two_point_attempt") != 1)).select(
        ["game_id", "play_id", "posteam", "qb_dropback", "receiver_player_id", "rusher_player_id",
         "air_yards", "yardline_100", "pass_attempt"])
    part = nfl.load_participation(seasons).select(
        [pl.col("nflverse_game_id").alias("game_id"), "play_id", "offense_players"])
    plays = pbp.join(part, on=["game_id", "play_id"], how="left")
    team = defaultdict(lambda: defaultdict(float))
    me = defaultdict(lambda: defaultdict(float))
    for r in plays.iter_rows(named=True):
        t = team[(r["game_id"], r["posteam"])]
        drop = bool(r["qb_dropback"])
        rz = r["yardline_100"] is not None and r["yardline_100"] <= 20
        gl = r["yardline_100"] is not None and r["yardline_100"] <= 5
        t["plays"] += 1
        t["dropbacks"] += drop
        t["has_participation"] += bool(r["offense_players"])
        air = float(r["air_yards"] or 0) if r["receiver_player_id"] else 0.0
        if r["receiver_player_id"]:
            t["targets"] += 1
            t["air"] += air
            t["rz_targets"] += rz
            m = me[(r["game_id"], r["receiver_player_id"])]
            m["targets"] += 1
            m["air"] += air
            m["rz_targets"] += rz
        if r["rusher_player_id"] and not drop:
            t["carries"] += 1
            t["rz_carries"] += rz
            t["gl_carries"] += gl
            m = me[(r["game_id"], r["rusher_player_id"])]
            m["rz_carries"] += rz
            m["gl_carries"] += gl
        for pid in (r["offense_players"] or "").split(";"):
            if pid:
                m = me[(r["game_id"], pid)]
                m["snaps"] += 1
                m["routes"] += drop
    xfp = {}
    for r in nfl.load_ff_opportunity(seasons).iter_rows(named=True):
        if r["player_id"] and r["game_id"]:
            xfp[(r["game_id"], r["player_id"])] = sum(float(r[c] or 0) * sw.get(k, 0) for c, k in XFP_COMPONENTS.items())
    out = defaultdict(list)
    for p in history.players.values():
        t = team.get((p.game_id, p.team_id))
        m = me.get((p.game_id, p.player_id), {})
        if not t:
            continue
        has_part = t["has_participation"] > 0.5 * t["plays"]
        out[p.player_id].append({
            "kickoff": p.kickoff, "game_id": p.game_id,
            "fp": score(p.stats, internal), "xfp": xfp.get((p.game_id, p.player_id)),
            "targets": p.stats["targets"], "carries": p.stats["rushing_attempts"],
            "pass_att": p.stats["passing_attempts"],
            "tgt_share": p.stats["targets"] / t["targets"] if t["targets"] else 0.0,
            "carry_share": p.stats["rushing_attempts"] / t["carries"] if t["carries"] else 0.0,
            "snap_share": m.get("snaps", 0) / t["plays"] if has_part else None,
            "route_share": m.get("routes", 0) / t["dropbacks"] if has_part and t["dropbacks"] else None,
            "routes": m.get("routes", 0) if has_part else None,
            "air_share": m.get("air", 0) / t["air"] if t["air"] > 0 else 0.0,
            "air": m.get("air", 0),
            "rz_tgt_share": m.get("rz_targets", 0) / t["rz_targets"] if t["rz_targets"] else 0.0,
            "rz_carry_share": m.get("rz_carries", 0) / t["rz_carries"] if t["rz_carries"] else 0.0,
            "gl_carry_share": m.get("gl_carries", 0) / t["gl_carries"] if t["gl_carries"] else 0.0})
    for games in out.values():
        games.sort(key=lambda g: g["kickoff"])
    return out


def ewma(values: list, half_life: float = HALF_LIFE):
    pairs = [(i, v) for i, v in enumerate(values) if v is not None]
    if not pairs:
        return np.nan
    n = len(values)
    w = np.array([0.5 ** ((n - 1 - i) / half_life) for i, _ in pairs])
    return float(np.dot(w, [v for _, v in pairs]) / w.sum())


def features(row: dict, games: list[dict]) -> dict:
    prior = [g for g in games if g["kickoff"] < row["kickoff"]][-PLAYER_GAMES:]
    f = {"games": len(prior)}
    if not prior:
        return f
    def col(k):
        return [g[k] for g in prior]
    for k in ("fp", "targets", "carries", "pass_att", "tgt_share", "carry_share", "xfp", "snap_share",
              "route_share", "air_share", "rz_tgt_share", "rz_carry_share", "gl_carry_share"):
        f[k] = ewma(col(k))
    f["fp_minus_xfp"] = f["fp"] - f["xfp"] if not np.isnan(f["xfp"]) else np.nan
    routes = sum(g["routes"] for g in prior if g["routes"] is not None)
    route_targets = sum(g["targets"] for g in prior if g["routes"] is not None)
    f["tprr"] = route_targets / routes if routes >= 20 else np.nan
    tgts = sum(col("targets"))
    f["adot"] = sum(col("air")) / tgts if tgts >= 5 else np.nan
    f["wopr"] = 1.5 * f["tgt_share"] + 0.7 * f["air_share"]
    last = prior[-1]
    f["snap_share_last"] = last["snap_share"] if last["snap_share"] is not None else np.nan
    f["route_share_last"] = last["route_share"] if last["route_share"] is not None else np.nan
    f["snap_trend"] = f["snap_share_last"] - f["snap_share"]
    f["xfp_last"] = last["xfp"] if last["xfp"] is not None else np.nan
    return f


def matrix(rows: list[dict], names: list[str], base: str) -> np.ndarray:
    pos = [[float(r["position"] == p) for p in POSITIONS] for r in rows]
    # The Sleeper-based correction may also see the engine; the engine-based
    # one never sees Sleeper, so it measures the engine on its own data.
    cols = [[r[base]] + ([r["engine"]] if base == "sleeper" else []) for r in rows]
    feats = [[r["f"].get(n, np.nan) for n in names] for r in rows]
    return np.hstack([np.array(pos), np.array(cols, dtype=float), np.array(feats, dtype=float)])


def loso(rows: list[dict], names: list[str], base: str) -> np.ndarray:
    """Leave-one-season-out residual correction on top of `base` ('sleeper' or 'engine')."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    pred = np.empty(len(rows))
    seasons = np.array([r["season"] for r in rows])
    X = matrix(rows, names, base)
    y = np.array([r["actual"] - r[base] for r in rows])
    for s in DEV:
        train, test = seasons != s, seasons == s
        model = HistGradientBoostingRegressor(loss="absolute_error", learning_rate=0.05, max_iter=300,
                                              max_leaf_nodes=15, min_samples_leaf=200, l2_regularization=1.0,
                                              random_state=SEED)
        model.fit(X[train], y[train])
        pred[test] = np.array([r[base] for r, keep in zip(rows, test) if keep]) + model.predict(X[test])
    return pred


def symmetric_pool(rows: list[dict], a: str, b: str) -> list[dict]:
    groups = defaultdict(list)
    for r in rows:
        groups[(r["season"], r["week"], r["position"])].append(r)
    out = []
    for (_, _, position), members in groups.items():
        n = GATE_POOL[position]
        keep = {id(r) for r in sorted(members, key=lambda r: -r[a])[:n]}
        keep |= {id(r) for r in sorted(members, key=lambda r: -r[b])[:n]}
        out += [r for r in members if id(r) in keep]
    return out


def compare(rows: list[dict], a: str, b: str) -> dict:
    """Paired |a - actual| - |b - actual| on the pool chosen by a or b. Negative: a better."""
    pool = symmetric_pool(rows, a, b)
    def one(sel):
        diffs = defaultdict(list)
        for r in sel:
            diffs[(r["season"], r["week"])].append(abs(r[a] - r["actual"]) - abs(r[b] - r["actual"]))
        flat = [d for v in diffs.values() for d in v]
        ci = week_bootstrap_ci(diffs, draws=DRAWS, seed=SEED)
        return {"n": len(sel), f"{a}_mae": round(float(np.mean([abs(r[a] - r["actual"]) for r in sel])), 3),
                f"{b}_mae": round(float(np.mean([abs(r[b] - r["actual"]) for r in sel])), 3),
                "diff": round(float(np.mean(flat)), 3), "ci": [round(c, 3) for c in ci] if ci else None}
    return {"pooled": one(pool),
            **{str(s): one([r for r in pool if r["season"] == s]) for s in DEV},
            "by_position": {p: one([r for r in pool if r["position"] == p]) for p in POSITIONS}}


def signal(rows: list[dict]) -> dict:
    """Spearman correlation of each trailing feature with the actual score and with Sleeper's miss, by position."""
    from scipy.stats import spearmanr
    out = {}
    pool = symmetric_pool(rows, "sleeper", "engine")
    for p in POSITIONS:
        sel = [r for r in pool if r["position"] == p]
        out[p] = {}
        for n in BOX + ADVANCED:
            pairs = [(r["f"].get(n, np.nan), r["actual"], r["actual"] - r["sleeper"]) for r in sel]
            pairs = [x for x in pairs if not np.isnan(x[0])]
            if len(pairs) < 200:
                continue
            x, act, miss = map(np.array, zip(*pairs))
            out[p][n] = {"vs_actual": round(float(spearmanr(x, act).statistic), 3),
                         "vs_sleeper_miss": round(float(spearmanr(x, miss).statistic), 3), "n": len(pairs)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scoring", required=True)
    ap.add_argument("--cache", default="advanced_rows.pkl")
    args = ap.parse_args()
    scoring = json.load(open(args.scoring))
    cache = Path(args.cache)
    if cache.exists():
        rows = pickle.loads(cache.read_bytes())
    else:
        history = nflverse_history(list(HISTORY))
        rows = graded_rows(history, scoring, sleeper_to_gsis())
        usage = player_games(history, scoring)
        for r in rows:
            r["f"] = features(r, usage.get(r["player_id"], []))
        cache.write_bytes(pickle.dumps(rows))
    print("graded rows", len(rows), flush=True)
    for base in ("sleeper", "engine"):
        for label, names in (("box", BOX), ("box_advanced", BOX + ADVANCED)):
            pred = loso(rows, names, base)
            for r, v in zip(rows, pred):
                r[f"{base}_{label}"] = v
    out = {"evidence_type": "retrospective_research", "dev_seasons": DEV, "sealed": 2022,
           "rows": len(rows),
           "advanced_vs_box_on_sleeper": compare(rows, "sleeper_box_advanced", "sleeper_box"),
           "advanced_correction_vs_sleeper": compare(rows, "sleeper_box_advanced", "sleeper"),
           "box_correction_vs_sleeper": compare(rows, "sleeper_box", "sleeper"),
           "advanced_vs_box_on_engine": compare(rows, "engine_box_advanced", "engine_box"),
           "engine_advanced_vs_sleeper": compare(rows, "engine_box_advanced", "sleeper"),
           "engine_vs_sleeper": compare(rows, "engine", "sleeper"),
           "signal": signal(rows)}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
