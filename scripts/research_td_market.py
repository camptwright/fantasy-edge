"""Anytime-TD market vs the engines: which predicts who scores?

Run inside the evaluation container (needs the raw archive and the database):
    docker cp scripts/research_td_market.py fantasy-edge-evaluation-1:/tmp/td.py
    docker exec -w /app -e PYTHONPATH=/app fantasy-edge-evaluation-1 python /tmp/td.py

Market probabilities (frozen pregame quotes, td_market.frozen):
- raw: mean Yes implied probability across books (hold included).
- pin_adj: Pinnacle two-sided no-vig; other books shifted in log-odds by
  their mean gap to Pinnacle on overlapping players (no outcomes used).
- team_scaled: raw Poisson rates scaled down so a team's sum is at most
  c x implied points, c = rush+rec TDs per implied point (nflverse 2021-2025).
Engines: P(TD) = 1 - exp(-(rush TD + rec TD)) from frozen v2, v1 and ESPN stats.
Outcome: rush, receiving, fumble-recovery or special-teams TD; players with no
stat line are treated as not playing (anytime-TD bets void). Paired log-loss
CIs bootstrap whole games. docs/2026-10-18-td-market-research.md has results.
"""

import asyncio
import json
import math
import collections
import numpy as np
from sqlalchemy import select
from src.db.client import get_worker_db
from src.models.facts import Game, PlayerGameStat
from src.models.sleeper import SleeperLeague
from src.services import (
    td_market,
    espn_projections,
    projection_engine_v2_data as D,
    projection_engine_v2_prospective as P,
)
from src.services.projection_engine_prospective import archive_root
from src.services.fantasy_decision_models import CORE, offensive_weights


def logit(p):
    return math.log(p / (1 - p))


def expit(x):
    return 1 / (1 + math.exp(-x))


def lam(s, a="rushing_touchdowns", b="receiving_touchdowns"):
    return float(s.get(a, 0) + s.get(b, 0))


TD_KEYS = ("rushing_touchdowns", "receiving_touchdowns", "fumble_recovery_tds", "special_teams_tds")


async def main():
    # c: offensive rush+rec TDs per implied point, nflverse 2021-2025
    d, _ = D.load_release(P.cache_dir(), 2026)
    sums = collections.defaultdict(float)
    for (gid, _), p in d["players"].items():
        st = p.get("stats") or p
        sums[(gid, p["team"])] += float(st.get("rushing_touchdowns", 0) or 0) + float(
            st.get("receiving_touchdowns", 0) or 0
        )
    num = den = 0.0
    n = 0
    for (gid, team), td in sums.items():
        g = d["games"][gid]
        if not (2021 <= g["season"] <= 2025) or g["home_points"] is None:
            continue
        num += td
        den += g["home_points"] if team == g["home"] else g["away_points"]
        n += 1
    c = num / den
    print(f"c={c:.4f} TDs per implied point over {n} team-games")

    quotes = td_market.frozen()
    v2root = archive_root() / "v2" / "forecasts"
    v2 = {}
    for path in v2root.glob("*.json"):
        r = json.loads(path.read_text())
        if r["captured_at"] < r["kickoff"]:
            key = (r["game_id"], r["player_id"])
            if key not in v2 or r["captured_at"] < v2[key]["captured_at"]:
                v2[key] = r  # first capture, any version
    v1 = {}
    for path in (archive_root() / "forecasts").glob("*.json"):
        r = json.loads(path.read_text())
        if r["captured_at"] < r["kickoff"]:
            key = (r["game_id"], r["player_id"])
            if key not in v1 or r["captured_at"] > v1[key]["captured_at"]:
                v1[key] = r
    espn = espn_projections.frozen()
    by_player = collections.defaultdict(dict)
    for (gid, pid, book), q in quotes.items():
        by_player[(gid, pid)][book] = q
    print(
        "quotes", len(quotes), "player-games", len(by_player), "books", collections.Counter(b for (_, _, b) in quotes)
    )
    # per-book shift to pinnacle no-vig, logit space, from overlap (no outcomes used)
    shifts = {}
    for book in ("draftkings", "betmgm", "caesars"):
        diffs = []
        for books in by_player.values():
            pin = books.get("pinnacle")
            if pin and pin["no"] and book in books:
                py, pn = td_market.implied(pin["yes"]), td_market.implied(pin["no"])
                diffs.append(logit(py / (py + pn)) - logit(td_market.implied(books[book]["yes"])))
        shifts[book] = (float(np.mean(diffs)) if diffs else None, len(diffs))
    print("shifts to pinnacle no-vig (logit)", shifts)
    async with get_worker_db() as db:
        games = {
            str(g.id): g
            for g in (
                await db.scalars(select(Game).where(Game.sport == "nfl", Game.season == 2026, Game.week >= 6))
            ).all()
        }
        rows = (
            await db.execute(
                select(
                    PlayerGameStat.game_id, PlayerGameStat.player_id, PlayerGameStat.stat_type, PlayerGameStat.value
                ).where(PlayerGameStat.game_id.in_([g.id for g in games.values() if g.status == "final"]))
            )
        ).all()
        league = (await db.scalars(select(SleeperLeague).where(SleeperLeague.name == "2016 Warriors"))).first()
    actual = collections.defaultdict(dict)
    for gid, pid, st, v in rows:
        actual[(str(gid), str(pid))][st] = float(v or 0)
    weights = {CORE[k]: w for k, w in offensive_weights(league.scoring_settings).items() if k in CORE}
    out = []
    for (gid, pid), books in by_player.items():
        g = games.get(gid)
        if g is None or g.status != "final":
            continue
        a = actual.get((gid, pid))
        if a is None:
            continue  # did not record a stat line: treated as not playing (bet void)
        scored = sum(a.get(k, 0) for k in TD_KEYS) >= 1
        raw = float(np.mean([td_market.implied(q["yes"]) for q in books.values()]))
        adj = []
        for b, q in books.items():
            if b == "pinnacle" and q["no"]:
                py, pn = td_market.implied(q["yes"]), td_market.implied(q["no"])
                adj.append(py / (py + pn))
            elif shifts.get(b, (None,))[0] is not None:
                adj.append(expit(logit(td_market.implied(q["yes"])) + shifts[b][0]))
        f2 = v2.get((gid, pid))
        f1 = v1.get((gid, pid))
        e = espn.get((gid, pid))
        out.append(
            {
                "gid": gid,
                "pid": pid,
                "team": f2["team_id"] if f2 else None,
                "pos": f2["position"] if f2 else None,
                "implied": f2["implied_points"] if f2 else None,
                "y": int(scored),
                "raw": raw,
                "pin_adj": float(np.mean(adj)) if adj else None,
                "v2": 1 - math.exp(-lam(f2["stats"])) if f2 else None,
                "v2_lam": lam(f2["stats"]) if f2 else None,
                "v1": 1 - math.exp(-lam(f1["stats"])) if f1 else None,
                "espn": 1 - math.exp(-lam(e["stats"], "rush_td", "rec_td")) if e else None,
                "v2_stats": f2["stats"] if f2 else None,
                "actual_pts": sum(a.get(s, 0) * w for s, w in weights.items()),
            }
        )
    # team scaling: sum of raw lambdas per team -> c * implied
    team = collections.defaultdict(list)
    for r in out:
        if r["team"]:
            team[(r["gid"], r["team"])].append(r)
    ratios = []
    for rs in team.values():
        s = sum(-math.log(1 - r["raw"]) for r in rs)
        target = c * rs[0]["implied"]
        ratios.append(s / target)
        for r in rs:
            r["team_scaled"] = 1 - math.exp(-(-math.log(1 - r["raw"])) * min(1.0, target / s))
    print(
        f"raw market lambda sum / (c*implied): median {np.median(ratios):.3f} (IQR {np.quantile(ratios, 0.25):.3f}-{np.quantile(ratios, 0.75):.3f}), teams {len(ratios)}"
    )
    analyse(out)
    print("rows", len(out), "scored", sum(r["y"] for r in out))


def analyse(rows):
    def brier(p, y):
        return (p - y) ** 2

    def ll(p, y):
        p = min(max(p, 1e-4), 1 - 1e-4)
        return -(y * math.log(p) + (1 - y) * math.log(1 - p))

    # ESPN's frozen projections are missing for some weeks; compare it on its own subset.
    methods = ["raw", "pin_adj", "team_scaled", "v2", "v1"]
    common = [r for r in rows if all(r.get(m) is not None for m in methods)]
    with_espn = [r for r in common if r.get("espn") is not None]
    if with_espn:
        d = [ll(r["espn"], r["y"]) - ll(r["v2"], r["y"]) for r in with_espn]
        print(f"espn subset rows {len(with_espn)} games {len({r['gid'] for r in with_espn})}: logloss vs v2 {np.mean(d):+.4f}")
    print("common rows", len(common), "scored", sum(r["y"] for r in common), "games", len({r["gid"] for r in common}))
    rng = np.random.default_rng(7)
    gids = sorted({r["gid"] for r in common})

    def ci(diff):  # game-cluster bootstrap of mean paired diff
        by = collections.defaultdict(list)
        for r, x in zip(common, diff):
            by[r["gid"]].append(x)
        ms = [np.mean(np.concatenate([by[g] for g in rng.choice(gids, len(gids))])) for _ in range(4000)]
        return np.quantile(ms, [0.025, 0.975])

    for m in methods:
        b = [brier(r[m], r["y"]) for r in common]
        losses = [ll(r[m], r["y"]) for r in common]
        mean_p = np.mean([r[m] for r in common])
        line = f"{m:12s} brier {np.mean(b):.4f} logloss {np.mean(losses):.4f} mean_p {mean_p:.3f} (observed {np.mean([r['y'] for r in common]):.3f})"
        if m != "v2":
            dl = [ll(r[m], r["y"]) - ll(r["v2"], r["y"]) for r in common]
            lo, hi = ci(dl)
            line += f" | logloss vs v2 {np.mean(dl):+.4f} CI ({lo:+.4f},{hi:+.4f})"
        print(line)
    # calibration of best market method by bucket
    for m in ("pin_adj", "v2"):
        print(
            m,
            "calibration:",
            [
                (
                    f"{lo:.1f}-{hi:.1f}",
                    len(s),
                    round(np.mean([r[m] for r in s]), 3),
                    round(np.mean([r["y"] for r in s]), 3),
                )
                for lo, hi in ((0, 0.15), (0.15, 0.3), (0.3, 0.45), (0.45, 1))
                if (s := [r for r in common if lo <= r[m] < hi])
            ],
        )
    # fantasy points: replace v2 TD expectation with market lambda (6 pts per rush/rec TD, Warriors scoring weights)
    dpts = []
    for r in common:
        lam_v2 = r["v2_lam"]
        lam_m = -math.log(1 - r["pin_adj"])
        dpts.append(6 * (lam_m - lam_v2))
    print("market minus v2 TD-points per player: mean", round(np.mean(dpts), 3), "sd", round(np.std(dpts), 3))
    for w in (0.25, 0.5):
        bl = [
            ll(1 - math.exp(-(w * -math.log(1 - r["pin_adj"]) + (1 - w) * r["v2_lam"])), r["y"]) - ll(r["v2"], r["y"])
            for r in common
        ]
        lo, hi = ci(bl)
        print(f"blend market w={w}: logloss vs v2 {np.mean(bl):+.4f} CI ({lo:+.4f},{hi:+.4f})")


asyncio.run(main())
