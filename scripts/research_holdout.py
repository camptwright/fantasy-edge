"""Pre-registered holdout test of projection engine v1 on 2023 and 2024.

Protocol: docs/2026-10-12-engine-research.md, "Pre-registered holdout test of
engine v1" (committed in cc42d04 before this script existed). Rebuilds the
engine's inputs from public nflverse data instead of the DB, which holds no
2023/2024 stats, and grades engine and Sleeper projections on the same
players. Retrospective evidence only: it never touches the prospective gate.

Needs nflreadpy (local .venv, not the containers) and no database:
    .venv/bin/python -m scripts.research_holdout --scoring warriors_scoring.json
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from collections import defaultdict
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np

from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.game_environment import implied_points
from src.services.projection_engine import DEFAULT, History, PlayerGame, TeamGame, compute, score
from src.services.projection_engine_prospective import week_bootstrap_ci

SLEEPER = "https://api.sleeper.app/v1/projections/nfl/regular/{season}/{week}"
EASTERN = ZoneInfo("America/New_York")
UNION_POOL = {"QB": 25, "RB": 50, "WR": 60, "TE": 20}  # FantasyPros pool, every earlier figure
GATE_POOL = {"QB": 12, "RB": 24, "WR": 30, "TE": 12}  # projection_engine_prospective.POOL
DRAWS, SEED = 4000, 0
# nflverse weekly column -> engine stat
COLUMNS = {"targets": "targets", "receptions": "receptions", "receiving_yards": "receiving_yards",
           "receiving_tds": "receiving_touchdowns", "carries": "rushing_attempts",
           "rushing_yards": "rushing_yards", "rushing_tds": "rushing_touchdowns",
           "attempts": "passing_attempts", "completions": "passing_completions",
           "passing_yards": "passing_yards", "passing_tds": "passing_touchdowns",
           "passing_interceptions": "passing_interceptions",
           "passing_2pt_conversions": "passing_2pt_conversions",
           "rushing_2pt_conversions": "rushing_2pt_conversions",
           "receiving_2pt_conversions": "receiving_2pt_conversions"}
FUMBLES = ("sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost")


def kickoff(gameday: str, gametime: str | None) -> datetime:
    clock = gametime or "13:00"
    return datetime.fromisoformat(f"{gameday}T{clock}").replace(tzinfo=EASTERN)


def nflverse_history(seasons: list[int]) -> History:
    """The engine's History from nflverse schedules (closing lines) and weekly stats."""
    import nflreadpy as nfl
    games, teams, players, positions = {}, {}, {}, {}
    for g in nfl.load_schedules(seasons).iter_rows(named=True):
        if g["game_type"] != "REG" or g["home_score"] is None:
            continue
        games[g["game_id"]] = SimpleNamespace(
            id=g["game_id"], season=g["season"], week=g["week"], game_type="REG", status="final",
            game_time=kickoff(g["gameday"], g["gametime"]), home_team_id=g["home_team"],
            away_team_id=g["away_team"], spread_line=g["spread_line"], total_line=g["total_line"])
    for r in nfl.load_player_stats(seasons, summary_level="week").iter_rows(named=True):
        game = games.get(r["game_id"])
        if game is None or r["team"] not in (game.home_team_id, game.away_team_id):
            continue
        stats = {stat: float(r[col] or 0) for col, stat in COLUMNS.items()}
        stats["fumbles_lost"] = float(sum(r[c] or 0 for c in FUMBLES))
        p = PlayerGame(r["player_id"], game.id, r["team"], game.game_time, stats)
        players[(p.player_id, p.game_id)] = p
        positions[p.player_id] = r["position"]
        t = teams.setdefault((game.id, r["team"]), TeamGame(game.id, r["team"], game.game_time))
        t.pass_attempts += stats["passing_attempts"]
        t.carries += stats["rushing_attempts"]
        t.targets += stats["targets"]
    for t in teams.values():
        g = games[t.game_id]
        if g.spread_line is None or g.total_line is None:
            continue
        home_spread = -float(g.spread_line)  # nflverse: positive when home is favoured
        home, away = implied_points(float(g.total_line), home_spread)
        is_home = t.team_id == g.home_team_id
        t.implied_points, t.spread = (home, home_spread) if is_home else (away, -home_spread)
    return History(games, teams, players, positions)


def sleeper_to_gsis() -> dict[str, str]:
    import nflreadpy as nfl
    ids = nfl.load_ff_playerids()
    out = {}
    for s, g in zip(ids["sleeper_id"].to_list(), ids["gsis_id"].to_list()):
        if s is not None and g:
            out[str(int(s)) if isinstance(s, float) else str(s)] = g
    return out


def sleeper_week(season: int, week: int) -> dict:
    with urllib.request.urlopen(SLEEPER.format(season=season, week=week), timeout=60) as r:
        return {k: v for k, v in json.load(r).items() if isinstance(v, dict) and v}


def rows_for(history: History, keys, scoring: dict, crosswalk: dict) -> list[dict]:
    sw = offensive_weights(scoring)
    internal = {CORE[k]: w for k, w in sw.items() if k in CORE}
    by_week = defaultdict(list)
    for g in history.games.values():
        by_week[(g.season, g.week)].append(g)
    rows = []
    for key in keys:
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
            rows.append({"season": key[0], "week": key[1], "position": proj.position,
                         "engine": score(proj.stats, internal),
                         "sleeper": sum(float(s.get(k, 0) or 0) * w for k, w in sw.items()),
                         "actual": score(got.stats, internal)})
    return rows


def pool(rows: list[dict], sizes: dict, union: bool, symmetric: bool = False) -> list[dict]:
    groups = defaultdict(list)
    for r in rows:
        groups[(r["season"], r["week"], r["position"])].append(r)
    out = []
    for (_, _, position), members in groups.items():
        n = sizes.get(position, 0)
        keep = {id(r) for r in sorted(members, key=lambda r: -r["sleeper"])[:n]}
        if union:
            keep |= {id(r) for r in sorted(members, key=lambda r: -r["actual"])[:n]}
        if symmetric:
            keep |= {id(r) for r in sorted(members, key=lambda r: -r["engine"])[:n]}
        out += [r for r in members if id(r) in keep]
    return out


def paired(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    diffs = defaultdict(list)
    for r in rows:
        diffs[(r["season"], r["week"])].append(abs(r["engine"] - r["actual"]) - abs(r["sleeper"] - r["actual"]))
    ci = week_bootstrap_ci(diffs, draws=DRAWS, seed=SEED)
    return {"n": len(rows), "weeks": len(diffs),
            "engine_mae": round(float(np.mean([abs(r["engine"] - r["actual"]) for r in rows])), 3),
            "sleeper_mae": round(float(np.mean([abs(r["sleeper"] - r["actual"]) for r in rows])), 3),
            "engine_minus_sleeper": round(float(np.mean([d for v in diffs.values() for d in v])), 3),
            "ci": [round(c, 3) for c in ci] if ci else None}


def report(rows: list[dict]) -> dict:
    out = {}
    # symmetric_pool is exploratory (added after the registered results were
    # seen): top-N by either source's projection, so neither the outcome nor
    # one source's ranking chooses who is graded.
    for name, sizes, union, symmetric in (("union_pool", UNION_POOL, True, False),
                                          ("gate_pool", GATE_POOL, False, False),
                                          ("symmetric_pool", GATE_POOL, False, True)):
        selected = pool(rows, sizes, union, symmetric)
        seasons = sorted({r["season"] for r in selected})
        out[name] = {"pooled": paired(selected),
                     **{str(s): paired([r for r in selected if r["season"] == s]) for s in seasons},
                     "by_position": {p: paired([r for r in selected if r["position"] == p]) for p in sizes}}
    return out


def verdict(primary: dict, seasons: list[int]) -> dict:
    """The pass bar exactly as registered."""
    failures = []
    ci = primary["pooled"]["ci"]
    if ci is None or ci[1] >= 0:
        failures.append("pooled_ci_upper_not_below_zero")
    failures += [f"{s}_point_estimate_not_below_zero" for s in seasons
                 if primary[str(s)]["engine_minus_sleeper"] >= 0]
    failures += [f"{p}_significantly_worse" for p, v in primary["by_position"].items()
                 if v.get("ci") and v["ci"][0] > 0]
    return {"passed": not failures, "failures": failures}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scoring", required=True, help="league scoring_settings JSON (2016 Warriors)")
    ap.add_argument("--check-only", action="store_true", help="fidelity check on 2025 W4-18 only")
    args = ap.parse_args()
    scoring = json.load(open(args.scoring))
    crosswalk = sleeper_to_gsis()
    out = {"protocol": "docs/2026-10-12-engine-research.md#pre-registered-holdout-test-of-engine-v1",
           "evidence_type": "retrospective_holdout", "serving_promoted": False}
    check = report(rows_for(nflverse_history([2024, 2025]), [(2025, w) for w in range(4, 19)], scoring, crosswalk))
    fidelity = check["union_pool"]["pooled"]
    out["fidelity_2025"] = {**fidelity, "target": {"engine_mae": 5.83, "sleeper_mae": 6.04},
                            "within_tolerance": abs(fidelity["engine_mae"] - 5.83) <= 0.10
                            and abs(fidelity["sleeper_mae"] - 6.04) <= 0.10}
    if not args.check_only and out["fidelity_2025"]["within_tolerance"]:
        holdout = [2023, 2024]
        rows = rows_for(nflverse_history([2022, 2023, 2024]),
                        [(s, w) for s in holdout for w in range(1, 19)], scoring, crosswalk)
        out["holdout"] = report(rows)
        out["verdict"] = verdict(out["holdout"]["union_pool"], holdout)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
