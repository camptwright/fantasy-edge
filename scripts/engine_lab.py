"""Engine v2 lab: rolling-origin development and ablation of projection_engine_v2.

Plan: docs/2026-10-15-engine-v2-plan.md (W0 harness). No database: public
nflverse data (2019-2025) and Sleeper's historical weekly projections.

- History 2019-2025. Training rows start 2020 (2019 seeds trailing
  features and league rates). 2022 outcomes may train later weeks' models
  but 2022 is never graded here: it is the sealed confirmatory season.
- Rolling origin: each graded week refits every stage on games that kicked
  off before that week's first kickoff.
- Graded cohort: player-games with a Sleeper projection and a stat line;
  the v1 comparison uses the identical rows v1 projected
  (scripts/research_advanced_stats.py cache).
- Metrics: league-scored error on the symmetric pool (top 12/24/30/12 by
  Sleeper or the candidate), week-cluster bootstrap; per-stat MAE; slices by
  position, weeks 1-4 vs 5-18, and agreement.

    .venv/bin/python -m scripts.engine_lab build --scoring warriors_scoring.json --out lab
    .venv/bin/python -m scripts.engine_lab run --scoring warriors_scoring.json --out lab --configs ablation
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np

from scripts.research_holdout import GATE_POOL
from src.services import projection_engine_v2 as v2
from src.services import projection_engine_v2_data as D
from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.projection_engine_prospective import week_bootstrap_ci

SEASONS = list(range(2019, 2027))  # 2026: weeks played so far, for the frozen-baseline check
TRAIN_FROM = 2020
SEALED = 2022
GRADED = (2023, 2024, 2025)
SLEEPER = "https://api.sleeper.app/v1/projections/nfl/regular/{season}/{week}"
DRAWS, SEED = 4000, 0
X_COLUMNS = {"receptions_exp": "x_receptions", "rec_yards_gained_exp": "x_receiving_yards",
             "rec_touchdown_exp": "x_receiving_touchdowns", "rush_yards_gained_exp": "x_rushing_yards",
             "rush_touchdown_exp": "x_rushing_touchdowns", "pass_completions_exp": "x_passing_completions",
             "pass_yards_gained_exp": "x_passing_yards", "pass_touchdown_exp": "x_passing_touchdowns",
             "pass_interception_exp": "x_passing_interceptions"}


def sleeper_week(cache: Path, season: int, week: int) -> dict:
    path = cache / f"{season}_{week}.json"
    if not path.exists():
        with urllib.request.urlopen(SLEEPER.format(season=season, week=week), timeout=60) as r:
            path.write_text(r.read().decode())
    return json.loads(path.read_text())


# ---------------------------------------------------------------- build

def build(out: Path) -> dict:
    """Shared v2 records (projection_engine_v2_data.assemble) plus lab-only play-by-play and xFP detail."""
    import nflreadpy as nfl
    import polars as pl
    schedules = list(nfl.load_schedules(SEASONS).iter_rows(named=True))
    rosters = list(nfl.load_rosters_weekly(SEASONS).iter_rows(named=True))
    cache = out / "sleeper"
    cache.mkdir(parents=True, exist_ok=True)
    played = sorted({(g["season"], g["week"]) for g in schedules if g["game_type"] == "REG" and g["home_score"] is not None})
    sleeper = {}
    for season in SEASONS:
        for week in sorted({w for s, w in played if s == season}) if season >= TRAIN_FROM else (1,):
            sleeper[(season, week)] = sleeper_week(cache, season, week)
    data = D.assemble(schedules, nfl.load_player_stats(SEASONS, summary_level="week").iter_rows(named=True),
                      nfl.load_snap_counts(SEASONS).iter_rows(named=True), rosters,
                      nfl.load_ff_playerids().iter_rows(named=True), sleeper)
    team_pbp, player_pbp = {}, defaultdict(lambda: defaultdict(float))
    for season in SEASONS:
        pbp = nfl.load_pbp([season]).filter((pl.col("season_type") == "REG") & (pl.col("two_point_attempt") != 1)
                                            & pl.col("play_type").is_in(["pass", "run"]))
        rz = pl.col("yardline_100") <= 20
        neutral = ((pl.col("wp") >= 0.2) & (pl.col("wp") <= 0.8) & (pl.col("down") <= 3)
                   & (pl.col("half_seconds_remaining") > 120) & pl.col("xpass").is_not_null()).fill_null(False)
        rec = pl.col("receiver_player_id").is_not_null()
        rush = (pl.col("rush_attempt") == 1).fill_null(False)
        agg = pbp.group_by(["game_id", "posteam"]).agg(
            plays=pl.len(), dropbacks=pl.col("qb_dropback").fill_null(0).sum(),
            n_neutral=neutral.sum(), neutral_pass=(neutral & (pl.col("qb_dropback") == 1)).sum(),
            neutral_xpass=pl.when(neutral).then(pl.col("xpass")).otherwise(0.0).sum(),
            rz_targets=(rec & rz).fill_null(False).sum(), rz_carries=(rush & rz).fill_null(False).sum(),
            gl_carries=(rush & (pl.col("yardline_100") <= 5)).fill_null(False).sum())
        for r in agg.iter_rows(named=True):
            proe = (r["neutral_pass"] - r["neutral_xpass"]) / r["n_neutral"] if r["n_neutral"] >= 5 else None
            team_pbp[(r["game_id"], r["posteam"])] = {"plays": r["plays"], "dropbacks": r["dropbacks"], "proe": proe,
                                                      "rz_targets": r["rz_targets"], "rz_carries": r["rz_carries"],
                                                      "gl_carries": r["gl_carries"]}
        for r in pbp.filter(rec).group_by(["game_id", "receiver_player_id"]).agg(
                rz_tgt=rz.fill_null(False).sum(),
                ez_tgt=(pl.col("air_yards") >= pl.col("yardline_100")).fill_null(False).sum()).iter_rows(named=True):
            p = player_pbp[(r["game_id"], r["receiver_player_id"])]
            p["rz_tgt"], p["ez_tgt"] = r["rz_tgt"], r["ez_tgt"]
        for r in pbp.filter(rush & pl.col("rusher_player_id").is_not_null()).group_by(["game_id", "rusher_player_id"]).agg(
                rz_car=rz.fill_null(False).sum(), gl_car=(pl.col("yardline_100") <= 5).fill_null(False).sum(),
                scrambles=(pl.col("qb_scramble") == 1).fill_null(False).sum(),
                designed_runs=(pl.col("qb_scramble") != 1).fill_null(True).sum()).iter_rows(named=True):
            p = player_pbp[(r["game_id"], r["rusher_player_id"])]
            p.update({k: r[k] for k in ("rz_car", "gl_car", "scrambles", "designed_runs")})
        print("pbp", season, len(team_pbp), flush=True)
    xfp = {}
    for r in nfl.load_ff_opportunity(SEASONS).iter_rows(named=True):
        if r["game_id"] and r["player_id"]:
            xfp[(r["game_id"], r["player_id"])] = {name: float(r[c]) if r[c] is not None else None for c, name in X_COLUMNS.items()}
    for key, p in data["players"].items():
        tp = team_pbp.get((p["game_id"], p["team"]), {})
        p.update({"team_dropbacks": tp.get("dropbacks", 0.0), "team_rz_targets": tp.get("rz_targets", 0.0),
                  "team_rz_carries": tp.get("rz_carries", 0.0), "team_gl_carries": tp.get("gl_carries", 0.0)})
        p.update(player_pbp.get(key, {}))
        p.update(xfp.get(key, {}))
    for key, t in data["teams"].items():
        tp = team_pbp.get(key)
        if tp:
            t.update({"plays": tp["plays"], "dropbacks": tp["dropbacks"], "proe": tp["proe"]})
    (out / "records.pkl").write_bytes(pickle.dumps(data))
    return data


def build_availability(out: Path) -> dict:
    import nflreadpy as nfl
    import polars as pl
    games = pickle.loads((out / "records.pkl").read_bytes())["games"]
    weekly = [s for s in SEASONS if s <= 2024]
    snapshots = []
    for season in [s for s in SEASONS if s >= 2025]:
        snapshots += nfl.load_depth_charts([season]).filter(pl.col("gsis_id").is_not_null()).iter_rows(named=True)
    extra = D.availability(games, nfl.load_injuries(SEASONS).iter_rows(named=True),
                           nfl.load_rosters_weekly(SEASONS).iter_rows(named=True),
                           nfl.load_depth_charts(weekly).iter_rows(named=True), snapshots)
    (out / "availability.pkl").write_bytes(pickle.dumps(extra))
    print("availability", len(extra["out"]), "depth", len(extra["depth"]))
    return extra


def features(data: dict, scoring: dict) -> tuple[list[dict], list]:
    path = OUT_DIR[0] / "availability.pkl" if OUT_DIR[0] else None
    extra = pickle.loads(path.read_bytes()) if path and path.exists() else {"out": {}, "depth": {}}
    return D.features(data, extra, offensive_weights(scoring))


# ---------------------------------------------------------------- rolling origin

def run(team_rows: list[dict], rows: list, groups, weeks: list[tuple[int, int]]) -> np.ndarray:
    """Rolling-origin predictions (STATS columns) for every row in the graded weeks; NaN elsewhere."""
    tf = v2.Frame.from_rows(team_rows, list(v2.TEAM_FEATURES) + ["t_tpa"])
    team_y = {"pass_att": np.array([t["pass_att"] for t in team_rows], float),
              "carries": np.array([t["carries"] for t in team_rows], float)}
    team_kick = np.array([t["kickoff"].timestamp() for t in team_rows])
    frame = FRAME_CACHE.get(id(rows)) or v2.Frame.from_rows([r for r, _ in rows])
    FRAME_CACHE[id(rows)] = frame
    kick = np.array([m["kickoff"].timestamp() for _, m in rows])
    sw = np.array([(m["season"], m["week"]) for _, m in rows])
    out = np.full((len(rows), len(v2.STATS)), math.nan)
    for season, week in weeks:
        test = (sw[:, 0] == season) & (sw[:, 1] == week)
        if not test.any():
            continue
        cutoff = kick[test].min()
        model = v2.fit(tf, team_y, team_kick < cutoff, frame, kick < cutoff, groups)
        out[test] = v2.predict(model, frame, test)
    return out


FRAME_CACHE: dict = {}
OUT_DIR: list = [None]


# ---------------------------------------------------------------- grading

def pool(graded: list[dict], a: str, b: str) -> list[dict]:
    groups = defaultdict(list)
    for r in graded:
        groups[(r["season"], r["week"], r["position"])].append(r)
    out = []
    for (_, _, pos), m in groups.items():
        n = GATE_POOL[pos]
        keep = {id(r) for r in sorted(m, key=lambda r: -r[a])[:n]} | {id(r) for r in sorted(m, key=lambda r: -r[b])[:n]}
        out += [r for r in m if id(r) in keep]
    return out


def paired(sel: list[dict], a: str, b: str) -> dict:
    if not sel:
        return {"n": 0}
    diffs = defaultdict(list)
    for r in sel:
        diffs[(r["season"], r["week"])].append(abs(r[a] - r["actual"]) - abs(r[b] - r["actual"]))
    ci = week_bootstrap_ci(diffs, draws=DRAWS, seed=SEED)
    return {"n": len(sel), "a_mae": round(float(np.mean([abs(r[a] - r["actual"]) for r in sel])), 3),
            "b_mae": round(float(np.mean([abs(r[b] - r["actual"]) for r in sel])), 3),
            "diff": round(float(np.mean([d for v in diffs.values() for d in v])), 3),
            "ci": [round(c, 3) for c in ci] if ci else None}


def compare(graded: list[dict], a: str, b: str, seasons=GRADED) -> dict:
    sel = pool(graded, a, b)
    return {"pooled": paired(sel, a, b),
            **{str(s): paired([r for r in sel if r["season"] == s], a, b)["diff"] for s in seasons},
            "by_position": {p: {k: v for k, v in paired([r for r in sel if r["position"] == p], a, b).items() if k in ("diff", "ci")}
                            for p in v2.POSITIONS},
            "weeks_1_4": paired([r for r in sel if r["week"] <= 4], a, b),
            "weeks_5_18": paired([r for r in sel if r["week"] > 4], a, b)}


BLEND_GRID = np.round(np.arange(0.0, 1.0001, 0.05), 2)


def blend(oos: list[dict]) -> None:
    """W10: per position and phase (weeks 1-4 / 5-18), the v2 weight that minimised
    absolute error on earlier weeks' out-of-sample rows (both sources' starter pools)."""
    by_week = defaultdict(list)
    for g in oos:
        by_week[(g["season"], g["week"])].append(g)
    order = sorted(by_week)
    history = []
    for key in order:
        rows = by_week[key]
        for pos in v2.POSITIONS:
            early = key[1] <= 4
            past = [r for r in history if r["position"] == pos and (r["week"] <= 4) == early]
            w = 0.5
            if len(past) >= 200:
                a = np.array([r["v2"] for r in past])
                b = np.array([r["sleeper"] for r in past])
                y = np.array([r["actual"] for r in past])
                w = float(min(BLEND_GRID, key=lambda x: np.mean(np.abs(x * a + (1 - x) * b - y))))
            for r in rows:
                if r["position"] == pos:
                    r["blend_w"] = w
                    r["blend"] = w * r["v2"] + (1 - w) * r["sleeper"]
        history += [r for r in pool(rows, "v2", "sleeper")]


def stat_mae(rows, preds: np.ndarray, mask: np.ndarray) -> dict:
    actual = np.array([[r["stats"][s] for s in v2.STATS] for r, _ in rows])
    return {s: round(float(np.mean(np.abs(preds[mask, j] - actual[mask, j]))), 4)
            for j, s in enumerate(v2.STATS) if not s.endswith("2pt_conversions")}


CONFIGS = {
    "core": ("core",),
    **{f"core+{g}": ("core", g) for g in v2.GROUPS if g != "core"},
    "all": v2.GROUPS,
    # groups that earned their place in development, and need no play-by-play
    "lean": D.LEAN,
    **{f"all-{g}": tuple(x for x in v2.GROUPS if x != g) for g in v2.GROUPS if g != "core"},
}


def v1_points(history_seasons: list[int], weeks: list[tuple[int, int]], internal: dict) -> dict:
    """Engine v1 (DEFAULT params) league points per (season, week, gsis), point-in-time per week."""
    from scripts.research_holdout import nflverse_history
    from src.services.projection_engine import DEFAULT, compute, score
    history = nflverse_history(history_seasons)
    by_week = defaultdict(list)
    for g in history.games.values():
        by_week[(g.season, g.week)].append(g)
    out = {}
    for key in weeks:
        targets = []
        for g in by_week.get(key, []):
            home, away = history.teams.get((g.id, g.home_team_id)), history.teams.get((g.id, g.away_team_id))
            if home and away and home.implied_points is not None and away.implied_points is not None:
                targets.append((g, home.implied_points, away.implied_points, home.spread))
        if targets:
            cutoff = min(g.game_time for g, *_ in targets)
            for pid, proj in compute(history, targets, cutoff, DEFAULT).items():
                out[(*key, pid)] = score(proj.stats, internal)
    return out


def confirm(out: Path, config: str, season: int, team_rows, rows, internal: dict) -> dict:
    """The registered confirmatory test (docs/2026-10-15-engine-v2-plan.md, "Registered test")."""
    weeks = [(s, w) for s in (season - 1, season) for w in range(1, 19)]
    preds = run(team_rows, rows, CONFIGS[config], weeks)
    fp = v2.score(np.nan_to_num(preds), internal)
    v1 = v1_points([season - 1, season], [(season, w) for w in range(1, 19)], internal)
    oos = []
    for (r, m), p in zip(rows, fp):
        if m["season"] in (season - 1, season) and m["sleeper"] is not None:
            oos.append({"season": m["season"], "week": m["week"], "position": r["position"], "gsis": m["gsis"],
                        "v2": float(p), "sleeper": m["sleeper"], "v1": v1.get((m["season"], m["week"], m["gsis"])),
                        "actual": float(np.array([r["stats"][s] for s in v2.STATS]) @
                                        np.array([internal.get(s, 0.0) for s in v2.STATS]))})
    blend(oos)
    graded = [g for g in oos if g["season"] == season]
    both = [g for g in graded if g["v1"] is not None]
    result = {"season": season, "config": config, "cohort": len(graded), "v1_cohort": len(both),
              "v2_vs_v1": compare(both, "v2", "v1", (season,)),
              "v2_vs_sleeper_archive": compare(graded, "v2", "sleeper", (season,)),
              "blend_vs_sleeper_archive": compare(graded, "blend", "sleeper", (season,))}
    a, b, c = (result[k]["pooled"] for k in ("v2_vs_v1", "v2_vs_sleeper_archive", "blend_vs_sleeper_archive"))
    failures = []
    if not a["ci"] or a["ci"][1] >= 0:
        failures.append("v2_not_better_than_v1")
    if not b["ci"] or b["ci"][0] > 0:
        failures.append("v2_significantly_worse_than_sleeper_archive")
    if not c["ci"] or c["ci"][1] >= 0:
        failures.append("blend_not_better_than_sleeper_archive")
    failures += [f"{p}_significantly_worse_than_v1" for p, v in result["v2_vs_v1"]["by_position"].items()
                 if v.get("ci") and v["ci"][0] > 0]
    result["verdict"] = {"passed": not failures, "failures": failures}
    return result


def frozen_check(out: Path, frozen_dir: Path, config: str, team_rows, rows) -> dict:
    """2026 weeks against Sleeper projections frozen before kickoff (fantasy-prospective
    provider-weekly records), the one Sleeper baseline the archive leak cannot reach.
    v2 and a v1 reconstruction are scored with each league's own scoring."""
    import glob
    import nflreadpy as nfl
    from scripts.research_holdout import nflverse_history
    from src.services.projection_engine import DEFAULT, compute
    frozen = {}
    for path in glob.glob(str(frozen_dir / "*.json")):
        r = json.loads(Path(path).read_text())
        if r["league_id"].startswith("espn:") or r["prediction"].get("source") != "sleeper":
            continue
        key = (r["league_id"], r["week"], r["player_id"])
        if r["prediction"]["observed_at"] < r["kickoff"] and (key not in frozen or r["captured_at"] > frozen[key]["captured_at"]):
            frozen[key] = r
    ids = nfl.load_ff_playerids()
    s2g = {str(int(s)) if isinstance(s, float) else str(s): g for s, g in zip(ids["sleeper_id"].to_list(), ids["gsis_id"].to_list())
           if s is not None and g}
    weights = {}
    for lid in {k[0] for k in frozen}:
        with urllib.request.urlopen(f"https://api.sleeper.app/v1/league/{lid}", timeout=60) as resp:
            sc = json.load(resp)["scoring_settings"]
        weights[lid] = {CORE[k]: w for k, w in offensive_weights(sc).items() if k in CORE}
    weeks = sorted({k[1] for k in frozen if k[1] >= 2})
    preds = run(team_rows, rows, CONFIGS[config], [(2026, w) for w in weeks])
    v2_stats = {(m["week"], m["gsis"]): preds[i] for i, (_, m) in enumerate(rows)
                if m["season"] == 2026 and m["week"] in weeks}
    actual = {(m["week"], m["gsis"]): np.array([r["stats"][s] for s in v2.STATS]) for r, m in rows if m["season"] == 2026}
    history = nflverse_history([2025, 2026])
    v1_stats = {}
    by_week = defaultdict(list)
    for g in history.games.values():
        if g.season == 2026:
            by_week[g.week].append(g)
    for w in weeks:
        targets = []
        for g in by_week[w]:
            home, away = history.teams.get((g.id, g.home_team_id)), history.teams.get((g.id, g.away_team_id))
            if home and away and home.implied_points is not None and away.implied_points is not None:
                targets.append((g, home.implied_points, away.implied_points, home.spread))
        if targets:
            cutoff = min(g.game_time for g, *_ in targets)
            for pid, proj in compute(history, targets, cutoff, DEFAULT).items():
                v1_stats[(w, pid)] = proj.stats
    graded = []
    for (lid, week, pid), r in frozen.items():
        g = s2g.get(pid)
        if week not in weeks or (week, g) not in actual or (week, g) not in v2_stats or r["position"] not in v2.POSITIONS:
            continue
        w = weights[lid]
        wv = np.array([w.get(s, 0.0) for s in v2.STATS])
        v1p = v1_stats.get((week, g))
        graded.append({"season": lid, "week": week, "position": r["position"], "gsis": g,
                       "sleeper": r["prediction"]["points"], "v2": float(np.nan_to_num(v2_stats[(week, g)]) @ wv),
                       "actual": float(actual[(week, g)] @ wv),
                       "v1": sum(v1p.get(s, 0.0) * c for s, c in w.items()) if v1p else None})
    both = [g for g in graded if g["v1"] is not None]
    pool_rows = lambda sel, a, b: pool([{**x, "season": (x["season"], x["week"])} for x in sel], a, b)  # noqa: E731
    def summary(sel, a, b):
        chosen = pool_rows(sel, a, b)
        for x in chosen:
            x["season"] = x["season"][0]
        diffs = defaultdict(list)
        for x in chosen:
            diffs[x["week"]].append(abs(x[a] - x["actual"]) - abs(x[b] - x["actual"]))
        ci = week_bootstrap_ci(diffs, draws=DRAWS, seed=SEED)
        return {"n": len(chosen), "weeks": sorted(diffs), f"{a}_mae": round(float(np.mean([abs(x[a] - x["actual"]) for x in chosen])), 3),
                f"{b}_mae": round(float(np.mean([abs(x[b] - x["actual"]) for x in chosen])), 3),
                "diff": round(float(np.mean([d for v in diffs.values() for d in v])), 3),
                "ci": [round(c, 3) for c in ci] if ci else None,
                "by_position": {p: round(float(np.mean([abs(x[a] - x["actual"]) - abs(x[b] - x["actual"])
                                                        for x in chosen if x["position"] == p])), 3) for p in v2.POSITIONS}}
    return {"frozen_rows": len(frozen), "graded": len(graded), "weeks": weeks,
            "v2_vs_frozen_sleeper": summary(graded, "v2", "sleeper"),
            "v1_vs_frozen_sleeper": summary(both, "v1", "sleeper"),
            "v2_vs_v1": summary(both, "v2", "v1"),
            "blend_half_vs_frozen_sleeper": summary([{**x, "blend": 0.5 * x["v2"] + 0.5 * x["sleeper"]} for x in graded], "blend", "sleeper")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "availability", "run", "frozen", "confirm"])
    ap.add_argument("--frozen-dir", help="fantasy-prospective/provider-weekly records (frozen Sleeper projections)")
    ap.add_argument("--scoring", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--configs", default="ablation", help="ablation, or comma-separated config names")
    ap.add_argument("--v1-cache", help="research_advanced_stats rows cache, for the v1 comparison")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.cmd == "build":
        build(out)
        return
    if args.cmd == "availability":
        build_availability(out)
        return
    OUT_DIR[0] = out
    scoring = json.load(open(args.scoring))
    internal = {CORE[k]: w for k, w in offensive_weights(scoring).items() if k in CORE}
    feat_path = out / "features.pkl"
    if feat_path.exists():
        team_rows, rows = pickle.loads(feat_path.read_bytes())
    else:
        team_rows, rows = features(pickle.loads((out / "records.pkl").read_bytes()), scoring)
        feat_path.write_bytes(pickle.dumps((team_rows, rows)))
    print("rows", len(rows), "team rows", len(team_rows), flush=True)
    if args.cmd == "confirm":
        result = confirm(out, args.configs, SEALED, team_rows, rows, internal)
        (out / f"confirm_{SEALED}_{args.configs}.json").write_text(json.dumps(result, indent=1))
        print(json.dumps(result, indent=1))
        return
    if args.cmd == "frozen":
        result = frozen_check(out, Path(args.frozen_dir), args.configs, team_rows, rows)
        (out / f"frozen_{args.configs}.json").write_text(json.dumps(result, indent=1))
        print(json.dumps(result, indent=1))
        return
    # predict from 2021 so the FP-level blend (W10) has out-of-sample history to learn from
    weeks = [(s, w) for s in range(2021, GRADED[-1] + 1) for w in range(1, 19)]
    names = list(CONFIGS) if args.configs == "ablation" else args.configs.split(",")
    v1 = {}
    if args.v1_cache:
        for r in pickle.loads(Path(args.v1_cache).read_bytes()):
            v1[(r["season"], r["week"], r["player_id"])] = r["engine"]
    results = {}
    graded_mask = np.array([m["season"] in GRADED and m["sleeper"] is not None for _, m in rows])
    oos_mask = np.array([m["season"] >= 2021 and m["sleeper"] is not None for _, m in rows])
    for name in names:
        preds = run(team_rows, rows, CONFIGS[name], weeks)
        fp = v2.score(np.nan_to_num(preds), internal)
        oos = []
        for (r, m), p, ok in zip(rows, fp, oos_mask):
            if ok:
                oos.append({"season": m["season"], "week": m["week"], "position": r["position"], "gsis": m["gsis"],
                               "v2": float(p), "sleeper": m["sleeper"], "actual": v2.score(
                                   np.array([[r["stats"][s] for s in v2.STATS]]), internal)[0],
                               "v1": v1.get((m["season"], m["week"], m["gsis"]))})
        blend(oos)
        graded = [g for g in oos if g["season"] in GRADED]
        (out / f"graded_{name}.pkl").write_bytes(pickle.dumps(graded))
        both = [g for g in graded if g["v1"] is not None]
        results[name] = {"cohort": len(graded), "v1_cohort": len(both),
                         "vs_sleeper": compare(graded, "v2", "sleeper"),
                         "blend_vs_sleeper": compare(graded, "blend", "sleeper"),
                         "blend_weights": sorted({(g["position"], g["week"] <= 4, g["blend_w"]) for g in graded
                                                  if g["season"] == GRADED[-1] and g["week"] in (1, 18)}),
                         "vs_v1_same_rows": compare(both, "v2", "v1") if both else None,
                         "stat_mae": stat_mae(rows, preds, graded_mask)}
        print(name, json.dumps({k: results[name][k] for k in ("cohort",)}),
              "vs_sleeper", results[name]["vs_sleeper"]["pooled"],
              "vs_v1", (results[name]["vs_v1_same_rows"] or {}).get("pooled"),
              "blend_vs_sleeper", results[name]["blend_vs_sleeper"]["pooled"], flush=True)
        if v1 and name == names[0]:
            results["v1_vs_sleeper_same_rows"] = compare([{**g, "v2": g["v1"]} for g in both], "v2", "sleeper")
    (out / f"results_{args.configs.replace(',', '_')}.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
