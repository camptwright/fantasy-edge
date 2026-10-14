"""Where does projection engine v1 lose points? Error decomposition against Sleeper.

Walk-forward engine projections (tune_projection_engine.week_slates, DEFAULT
params) and Sleeper's public weekly projections for the same player-weeks,
re-scored with one Sleeper league's rules, graded on box scores for players
who played, FantasyPros pool (top-N by Sleeper projection or actual, per
position-week). Reports:

- stat components: fantasy-point MAE and signed bias per stat (engine, Sleeper);
- volume: targets / carries / pass-attempt error (engine, Sleeper);
- calibration: slope of actual on projection, bias by projection bucket;
- segments: history depth, team change, returning from an absence, teammates
  missing (vacated targets), where the paired engine-Sleeper gap is largest.

Research only. Run in the worker environment:
    python -m scripts.diagnose_projection_engine [--league ID]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone

import httpx
import numpy as np
from sqlalchemy import select

from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.sleeper import SleeperLeague
from src.services.fantasy_decision_models import CORE, offensive_weights
from src.services.player_identity import resolve_platform_players
from src.services.projection_engine import DEFAULT, compute, load_history, score
from scripts.tune_projection_engine import POOL, WEEKS, week_slates

VOLUME = {"targets": "rec_tgt", "rushing_attempts": "rush_att", "passing_attempts": "pass_att"}


async def sleeper_week(client, season, week):
    r = await client.get(f"{get_settings().sleeper_base_url}/projections/nfl/regular/{season}/{week}")
    r.raise_for_status()
    return {str(pid): s for pid, s in r.json().items() if isinstance(s, dict) and s}


def summary(errors):
    a = np.array(errors, float)
    return {"n": len(a), "mae": round(float(np.mean(np.abs(a))), 3), "bias": round(float(np.mean(a)), 3)} if len(a) else {"n": 0}


async def run(league_id):
    weeks = [w for w in WEEKS if w != (2026, 6)] + [(2026, 1)]
    async with get_worker_db() as db:
        leagues = (await db.scalars(select(SleeperLeague).where(SleeperLeague.platform == "sleeper"))).all()
        league = next(lg for lg in leagues if league_id in (None, lg.league_id))
        history = await load_history(db, [2024, 2025, 2026], datetime.now(timezone.utc))
        async with httpx.AsyncClient(timeout=60) as c:
            sleeper = {k: await sleeper_week(c, *k) for k in weeks}
        ids = await resolve_platform_players(db, "sleeper", sorted({i for v in sleeper.values() for i in v}))
    sw = offensive_weights(league.scoring_settings)
    internal = {CORE[k]: w for k, w in sw.items() if k in CORE}
    inverse = {v: k for k, v in CORE.items()}
    slates = week_slates(history)

    # Per-player game lists for segment features.
    by_player = defaultdict(list)
    for p in history.players.values():
        by_player[p.player_id].append(p)
    for v in by_player.values():
        v.sort(key=lambda p: p.kickoff)
    by_game = defaultdict(list)
    for p in history.players.values():
        by_game[p.game_id].append(p)
    team_games = defaultdict(list)
    for g in history.games.values():
        for t in (g.home_team_id, g.away_team_id):
            team_games[t].append(g)
    for v in team_games.values():
        v.sort(key=lambda g: g.game_time)

    rows = []
    for key in sorted(weeks):
        if key not in slates:
            continue
        cutoff, targets, actual = slates[key]
        engine = compute(history, targets, cutoff, DEFAULT)
        sl = {str(ids[i].id): s for i, s in sleeper[key].items() if ids.get(i)}
        # Vacated targets: last-game targets of teammates who were on the team last week and do not play this week.
        played_now = {pid for pid, p in actual.items()}
        for pid, proj in engine.items():
            got = actual.get(pid)
            s = sl.get(str(pid))
            if got is None or got.game_id != proj.game_id or s is None:
                continue
            prior = [g for g in by_player[pid] if g.kickoff < cutoff]
            team_prior = [g for g in team_games[proj.team_id] if g.game_time < cutoff]
            last_team_game = team_prior[-1] if team_prior else None
            returning = bool(prior and last_team_game and prior[-1].game_id != last_team_game.id)
            vacated = 0.0
            if last_team_game is not None:
                for p in by_game[last_team_game.id]:
                    if (p.team_id == proj.team_id and p.player_id != pid
                            and p.player_id not in played_now):
                        vacated += p.stats.get("targets", 0.0)
            rows.append({
                "key": key, "position": proj.position, "games_used": proj.games_used,
                "team_change": bool(prior and prior[-1].team_id != proj.team_id),
                "returning": returning, "vacated_targets": vacated,
                "engine": score(proj.stats, internal), "sleeper": sum(float(s.get(k, 0)) * w for k, w in sw.items()),
                "actual": score(got.stats, internal),
                "components": {st: (proj.stats.get(st, 0.0) * w, float(s.get(inverse[st], 0)) * w, got.stats.get(st, 0.0) * w)
                               for st, w in internal.items() if st in proj.stats},
                "volume": {st: (proj.stats.get(st, 0.0), float(s.get(sk, 0)) if sk in s else None, got.stats.get(st, 0.0))
                           for st, sk in VOLUME.items()},
            })
    # Pool per (week, position).
    groups = defaultdict(list)
    for r in rows:
        groups[(r["key"], r["position"])].append(r)
    pool = []
    for (key, pos), members in groups.items():
        n = POOL[pos]
        keep = {id(r) for r in sorted(members, key=lambda r: -r["sleeper"])[:n]} | \
               {id(r) for r in sorted(members, key=lambda r: -r["actual"])[:n]}
        pool += [r for r in members if id(r) in keep]

    def paired(subset):
        e = [abs(r["engine"] - r["actual"]) for r in subset]
        s = [abs(r["sleeper"] - r["actual"]) for r in subset]
        return {"n": len(subset), "engine": round(float(np.mean(e)), 3) if e else None,
                "sleeper": round(float(np.mean(s)), 3) if s else None,
                "engine_minus_sleeper": round(float(np.mean(e) - np.mean(s)), 3) if e else None,
                "engine_bias": round(float(np.mean([r["engine"] - r["actual"] for r in subset])), 3) if e else None,
                "sleeper_bias": round(float(np.mean([r["sleeper"] - r["actual"] for r in subset])), 3) if e else None}

    out = {"league_id": league.league_id, "pool_rows": len(pool), "all_rows": len(rows)}
    for season in (2025, 2026):
        out[f"overall_{season}"] = paired([r for r in pool if r["key"][0] == season])
    out["by_position"] = {p: paired([r for r in pool if r["position"] == p]) for p in POOL}
    comp = defaultdict(lambda: {"engine": [], "sleeper": []})
    for r in pool:
        for st, (e, s, a) in r["components"].items():
            comp[(r["position"], st)]["engine"].append(e - a)
            comp[(r["position"], st)]["sleeper"].append(s - a)
    out["components"] = {f"{p}:{st}": {k: summary(v) for k, v in d.items()}
                         for (p, st), d in sorted(comp.items()) if np.mean(np.abs(d["engine"])) > 0.15}
    vol = defaultdict(lambda: {"engine": [], "sleeper": []})
    for r in pool:
        for st, (e, s, a) in r["volume"].items():
            if s is None or (st == "passing_attempts" and r["position"] != "QB"):
                continue
            if e == 0 and s == 0 and a == 0:
                continue
            vol[(r["position"], st)]["engine"].append(e - a)
            vol[(r["position"], st)]["sleeper"].append(s - a)
    out["volume"] = {f"{p}:{st}": {k: summary(v) for k, v in d.items()} for (p, st), d in sorted(vol.items())}
    cal = {}
    for p in POOL:
        sub = [r for r in pool if r["position"] == p]
        for src in ("engine", "sleeper"):
            x, y = np.array([r[src] for r in sub]), np.array([r["actual"] for r in sub])
            cal[f"{p}:{src}"] = round(float(np.polyfit(x, y, 1)[0]), 3) if len(sub) > 10 else None
    out["calibration_slope"] = cal
    buckets = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 100)]
    out["by_sleeper_bucket"] = {f"{lo}-{hi}": paired([r for r in pool if lo <= r["sleeper"] < hi]) for lo, hi in buckets}
    out["segments"] = {
        "games_used_0_1": paired([r for r in pool if r["games_used"] <= 1]),
        "games_used_2_3": paired([r for r in pool if 2 <= r["games_used"] <= 3]),
        "games_used_4_plus": paired([r for r in pool if r["games_used"] >= 4]),
        "team_change": paired([r for r in pool if r["team_change"]]),
        "returning_from_absence": paired([r for r in pool if r["returning"]]),
        "vacated_targets_6_plus": paired([r for r in pool if r["vacated_targets"] >= 6 and r["position"] in ("WR", "TE", "RB")]),
        "vacated_targets_0": paired([r for r in pool if r["vacated_targets"] == 0 and r["position"] in ("WR", "TE", "RB")]),
        "early_season_weeks_1_3": paired([r for r in pool if r["key"][1] <= 3]),
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league")
    print(json.dumps(asyncio.run(run(ap.parse_args().league)), indent=1, default=str))


if __name__ == "__main__":
    main()
