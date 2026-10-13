"""Offline research: team scoring split (offense/defense ratings) for game totals.

Model: src/services/team_model.py ScoringParams (538/nfelo-style log-error
updates per side, market resist against the closing total, offseason
reversion, a slowly moving league scoring level). Baseline: the serving
totals model (src/services/totals.py), each side the mean of its own running
scored average and the opponent's running allowed average. Market: closing
total_line. Fit on 2006-2014, test 2015-2025, walk-forward.

Usage: python -m scripts.research_totals_model --games games.csv [--config config/nfl_team_model.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import math

import numpy as np
from scipy.optimize import minimize
from scipy.stats import norm

from src.services import team_model as tm

TRAIN, TEST, SERVING_FROM = range(2006, 2015), range(2015, 2026), 2012
PARAMS = ["k", "resist", "reversion", "league_alpha", "hfa"]
START = [0.4, 3.0, 0.35, 0.01, 2.0]
sig = lambda v: 1 / (1 + math.exp(-v))
logit = lambda p: math.log(p / (1 - p))
# Unconstrained search space -> valid parameters (k, resist > 0; reversion, alpha in (0, 1)).
to_params = lambda q: [math.exp(q[0]), math.exp(q[1]), sig(q[2]), sig(q[3]), q[4]]
from_params = lambda x: [math.log(x[0]), math.log(x[1]), logit(x[2]), logit(x[3]), x[4]]


def load(path):
    out = []
    for r in csv.DictReader(open(path)):
        if not r["result"] or not r["total_line"] or int(r["season"]) < 2002:
            continue
        out.append({"season": int(r["season"]), "home": tm.RELOCATED.get(r["home_team"], r["home_team"]),
                    "away": tm.RELOCATED.get(r["away_team"], r["away_team"]), "neutral": r["location"] == "Neutral",
                    "hp": float(r["home_score"]), "ap": float(r["away_score"]), "line": float(r["total_line"])})
    return out


def model(games, x, state=None):
    s = tm.ScoringParams(**dict(zip(PARAMS, x)))
    ratings, league, season, preds = {}, (games[0]["hp"] + games[0]["ap"]) / 2 if games else 21.5, None, []
    for g in games:
        if g["season"] != season:
            season, ratings = g["season"], tm.rollover_scoring(s, ratings)
        oh, dh = ratings.get(g["home"], [0.0, 0.0])
        oa, da = ratings.get(g["away"], [0.0, 0.0])
        exp = tm.expected_points(s, league, oh, dh, oa, da, neutral=g["neutral"])
        preds.append(exp)
        league = tm.update_scoring(s, ratings, g["home"], g["away"], league, exp, (g["hp"], g["ap"]), g["line"])
    if state is not None:
        state.update({"ratings": ratings, "league": league})
    return np.array(preds)


def serving_baseline(games):
    """totals.py: running scored/allowed means since the start of the previous season."""
    sums, preds, season = {}, [], None
    for g in games:
        if g["season"] != season:
            season = g["season"]
            sums = {t: v for t, v in sums.items() if v["season"] >= season - 1}
        h = sums.get(g["home"]); a = sums.get(g["away"])
        if h and a and h["n"] >= 3 and a["n"] >= 3:
            preds.append((h["s"] / h["n"] + a["a"] / a["n"]) / 2 + (a["s"] / a["n"] + h["a"] / h["n"]) / 2)
        else:
            preds.append(None)
        for t, pf, pa in ((g["home"], g["hp"], g["ap"]), (g["away"], g["ap"], g["hp"])):
            v = sums.setdefault(t, {"s": 0.0, "a": 0.0, "n": 0, "season": season})
            v["s"] += pf; v["a"] += pa; v["n"] += 1; v["season"] = season
    return preds


def ou(pred, games, idx, sigma):
    y, ps = [], []
    for i in idx:
        g = games[i]
        total = g["hp"] + g["ap"]
        if total == g["line"] or pred[i] is None:
            continue
        y.append(float(total > g["line"]))
        ps.append(1 - norm.cdf((g["line"] - pred[i]) / sigma))
    p, y = np.clip(np.array(ps), 1e-4, 1 - 1e-4), np.array(y)
    return {"n": len(y), "brier": round(float(np.mean((p - y) ** 2)), 4),
            "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4)}


def fit(games, idx):
    totals = np.array([g["hp"] + g["ap"] for g in games])
    sides = np.array([[g["hp"], g["ap"]] for g in games])
    res = minimize(lambda q: float(np.mean((sides[idx] - model(games, to_params(q))[idx]) ** 2)), from_params(START),
                   method="Nelder-Mead", options={"maxiter": 1500, "xatol": 1e-4, "fatol": 1e-6})
    res.x = np.array(to_params(res.x))
    raw = model(games, res.x).sum(1)
    market = np.array([g["line"] for g in games])
    shape = lambda q: (1 / (1 + math.exp(-q[0])), q[1], math.exp(q[2]))
    rres = minimize(lambda q: float(np.mean((totals[idx] - np.array([tm.regress_total(
        tm.ScoringParams(mr_floor=shape(q)[0], mr_mid=shape(q)[1], mr_steep=shape(q)[2]), m, k)
        for m, k in zip(raw[idx], market[idx])])) ** 2)), [1.5, 2.0, 0.7], method="Nelder-Mead", options={"maxiter": 500})
    floor, mid, steep = shape(rres.x)
    rp = tm.ScoringParams(mr_floor=floor, mr_mid=mid, mr_steep=steep)
    final = np.array([tm.regress_total(rp, m, k) for m, k in zip(raw, market)])
    sigma = float(np.sqrt(np.mean((totals[idx] - final[idx]) ** 2)))
    return res.x, (floor, mid, steep), sigma, raw, final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", required=True)
    ap.add_argument("--config")
    args = ap.parse_args()
    games = load(args.games)
    seasons = np.array([g["season"] for g in games])
    totals = np.array([g["hp"] + g["ap"] for g in games])
    market = np.array([g["line"] for g in games])
    train = np.where(np.isin(seasons, list(TRAIN)))[0]
    test = np.where(np.isin(seasons, list(TEST)))[0]
    x, (floor, mid, steep), sigma, raw, final = fit(games, train)
    base = serving_baseline(games)
    btest = [i for i in test if base[i] is not None]
    mae = lambda p, ix: round(float(np.mean([abs(totals[i] - p[i]) for i in ix])), 3)
    report = {"train": [2006, 2014], "test": [2015, 2025],
              "params": dict(zip(PARAMS, map(lambda v: round(float(v), 4), x))),
              "regression": {"floor": round(floor, 3), "mid": round(mid, 3), "steep": round(steep, 3)}, "sigma": round(sigma, 3),
              "test_total_mae": {"serving_running_means": mae(base, btest), "rebuilt_raw": mae(raw, btest),
                                 "market_close": mae(market, btest), "rebuilt_regressed": mae(final, btest)},
              "test_over_under": {"serving_running_means": ou(base, games, btest, sigma), "rebuilt_raw": ou(raw, games, btest, sigma),
                                  "rebuilt_regressed": ou(final, games, btest, sigma)}}
    print(json.dumps(report, indent=1))
    if args.config:
        recent = np.where(seasons >= SERVING_FROM)[0]
        sx, (sf, sm, ss), ssig, _, _ = fit(games, recent)
        state = {}
        model(games, sx, state)
        artifact = json.load(open(args.config))
        artifact["scoring"] = {"params": {**dict(zip(PARAMS, map(float, sx))), "total_sigma": ssig, "mr_floor": sf,
                                          "mr_mid": sm, "mr_steep": min(ss, 50.0)},
                               "league": round(state["league"], 3),
                               "ratings": {t: [round(o, 3), round(d, 3)] for t, (o, d) in sorted(state["ratings"].items())},
                               "evidence": {k: report[k] for k in ("train", "test", "test_total_mae", "test_over_under")}}
        json.dump(artifact, open(args.config, "w"), indent=2)


if __name__ == "__main__":
    main()
