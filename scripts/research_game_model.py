"""Offline research: NFL game model rebuilt from published methods, vs the
serving Elo and the closing market.

Methods reconstructed from public sources (no code copied):
- FiveThirtyEight NFL Elo methodology: margin-aware updates, season-to-season
  reversion to the mean, home field, extra rest, starting-QB changes.
- nfelo (open methodology): log-scaled error updates; a "market resist" step
  that updates harder when the closing line was closer to the result than the
  model; regression of the model toward the market with a logistic S-curve in
  model/market disagreement (small disagreements collapse to the market,
  large ones keep a bounded opinion).

Data: nflverse games.csv (closing spread_line = home expected margin,
result = home - away). Parameters are fitted on TRAIN seasons only and frozen
for the TEST seasons, walk-forward (ratings only ever use past games).

Usage: python -m scripts.research_game_model --games games.csv [--out report.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.stats import norm

from src.services import team_model

TRAIN = range(2006, 2015)
TEST = range(2015, 2026)
SERVING_FROM = 2012


@dataclass
class Game:
    season: int
    week: int
    playoff: bool
    home: str
    away: str
    neutral: bool
    result: float
    spread: float  # market: home expected margin
    home_rest: int
    away_rest: int
    home_qb: str
    away_qb: str


def load(path: str) -> list[Game]:
    out = []
    for r in csv.DictReader(open(path)):
        if not r["result"] or not r["spread_line"] or int(r["season"]) < 2002:
            continue
        out.append(Game(int(r["season"]), int(r["week"]), r["game_type"] != "REG",
                        team_model.RELOCATED.get(r["home_team"], r["home_team"]), team_model.RELOCATED.get(r["away_team"], r["away_team"]),
                        r["location"] == "Neutral", float(r["result"]), float(r["spread_line"]),
                        int(r["home_rest"] or 7), int(r["away_rest"] or 7), r["home_qb_id"], r["away_qb_id"]))
    return out


# ---- the serving baseline (src/services/elo.py), replayed ---------------------------------
def serving_elo(games):
    R, preds = {}, []
    for g in games:
        h, a = R.get(g.home, 1500.0), R.get(g.away, 1500.0)
        p = 1 / (1 + 10 ** ((a - h - 65) / 400))
        preds.append(((h + 65 - a) / 25.0, p))
        actual = 1.0 if g.result > 0 else 0.0 if g.result < 0 else 0.5
        R[g.home], R[g.away] = h + 20 * (actual - p), a - 20 * (actual - p)
    return preds


# ---- the rebuilt points-rating model (src/services/team_model.py) --------------------------
PARAMS = ["k", "resist", "reversion", "hfa", "rest"]
START = [0.45, 2.0, 0.3, 2.5, 0.2]


def rebuilt(games, x, ratings_out=None):
    p = team_model.Params(**dict(zip(PARAMS, x)))
    R, season, preds = {}, None, []
    for g in games:
        if g.season != season:
            season = g.season
            R = team_model.rollover(p, R)
        h, a = R.get(g.home, 0.0), R.get(g.away, 0.0)
        m = team_model.expected_margin(p, h, a, neutral=g.neutral, rest_diff=g.home_rest - g.away_rest)
        preds.append(m)
        R[g.home], R[g.away] = team_model.update(p, h, a, m, g.result, g.spread)
    if ratings_out is not None:
        ratings_out.update(R)
    return np.array(preds)


def regress(model, market, mid, steep, floor):
    p = team_model.Params(mr_mid=mid, mr_steep=steep, mr_floor=floor)
    return np.array([team_model.regress_to_market(p, m, k) for m, k in zip(model, market)])


def fit(games, y, market, idx):
    res = minimize(lambda x: float(np.mean((y[idx] - rebuilt(games, x)[idx]) ** 2)), START, method="Nelder-Mead",
                   options={"maxiter": 800, "xatol": 1e-4, "fatol": 1e-5})
    raw = rebuilt(games, res.x)
    shape = lambda q: (q[0], math.exp(q[1]), 1 / (1 + math.exp(-q[2])))
    rres = minimize(lambda q: float(np.mean((y[idx] - regress(raw[idx], market[idx], *shape(q))) ** 2)),
                    [2.0, 0.7, 1.0], method="Nelder-Mead", options={"maxiter": 600})
    mid, steep, floor = shape(rres.x)
    final = regress(raw, market, mid, steep, floor)
    sigma = float(np.sqrt(np.mean((y[idx] - final[idx]) ** 2)))
    return res.x, (mid, steep, floor), sigma, raw, final


def metrics(pred_margin, prob, games, idx):
    y = np.array([g.result for g in games])[idx]
    won = (y > 0).astype(float)
    keep = y != 0
    m = pred_margin[idx]
    return {"n": int(len(idx)), "mae": round(float(np.mean(np.abs(y - m))), 3),
            "rmse": round(float(np.sqrt(np.mean((y - m) ** 2))), 3),
            "brier": round(float(np.mean((prob[idx][keep] - won[keep]) ** 2)), 4)}


def ats(final, market, games, idx, threshold):
    y = np.array([g.result for g in games])[idx]
    edge = final[idx] - market[idx]
    pick = np.abs(edge) >= threshold
    side = np.sign(edge[pick])
    cover = np.sign(y[pick] - market[idx][pick])
    graded = cover != 0
    wins = int(np.sum(side[graded] == cover[graded]))
    n = int(np.sum(graded))
    return {"threshold": threshold, "bets": n, "win_rate": round(wins / n, 4) if n else None,
            "breakeven": 0.5238}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", required=True)
    ap.add_argument("--out", help="research report json")
    ap.add_argument("--config", help="write the serving artifact (config/nfl_team_model.json)")
    args = ap.parse_args()
    games = load(args.games)
    seasons = np.array([g.season for g in games])
    market = np.array([g.spread for g in games])
    y = np.array([g.result for g in games])
    train = np.where(np.isin(seasons, list(TRAIN)))[0]
    test = np.where(np.isin(seasons, list(TEST)))[0]

    x, (mid, steep, floor), sigma, raw, final = fit(games, y, market, train)
    serving = serving_elo(games)
    serve_margin = np.array([s[0] for s in serving])
    serve_prob = np.array([s[1] for s in serving])
    prob = lambda m: norm.cdf(m / sigma)
    report = {
        "train": [TRAIN.start, TRAIN.stop - 1], "test": [TEST.start, TEST.stop - 1],
        "params": {**dict(zip(PARAMS, map(lambda v: round(float(v), 4), x))), "sigma": round(sigma, 3)},
        "regression": {"mid": round(float(mid), 3), "steep": round(float(steep), 3), "floor": round(floor, 3)},
        "test_metrics": {
            "serving_elo": metrics(serve_margin, serve_prob, games, test),
            "rebuilt_raw": metrics(raw, prob(raw), games, test),
            "market_close": metrics(market, prob(market), games, test),
            "rebuilt_market_regressed": metrics(final, prob(final), games, test),
        },
        "test_ats": [ats(final, market, games, test, t) for t in (0.5, 1.0, 1.5, 2.0, 3.0)],
        "test_ats_raw": [ats(raw, market, games, test, t) for t in (1.0, 3.0, 5.0)],
    }
    print(json.dumps(report, indent=2))
    if args.out:
        json.dump(report, open(args.out, "w"), indent=2)
    if args.config:
        # Serving fit: same structure refitted on the most recent seasons (the
        # held-out test above is the evidence); ratings as of the last complete season.
        recent = np.where(seasons >= SERVING_FROM)[0]
        sx, (smid, ssteep, sfloor), ssigma, _, _ = fit(games, y, market, recent)
        last = max(g.season for g in games if g.week >= 18 or g.playoff)
        ratings: dict = {}
        rebuilt([g for g in games if g.season <= last], sx, ratings)
        artifact = {
            "recipe": "nfl_team_model_v2", "fitted_on": [SERVING_FROM, last], "ratings_through_season": last,
            "params": {**dict(zip(PARAMS, map(float, sx))), "sigma": ssigma, "mr_mid": smid, "mr_steep": ssteep,
                       "mr_floor": sfloor},
            "ratings": {t: round(float(v), 3) for t, v in sorted(ratings.items())},
            "evidence": {k: report[k] for k in ("train", "test", "test_metrics", "test_ats")},
            "sources": ["nflverse games.csv (closing spread_line)", "FiveThirtyEight NFL Elo methodology",
                        "nfelo open methodology (market resist, market regression)"],
        }
        json.dump(artifact, open(args.config, "w"), indent=2)


if __name__ == "__main__":
    main()
