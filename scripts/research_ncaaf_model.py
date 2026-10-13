"""Offline research: NCAAF team model (margin + scoring split) vs the serving Elo and the market.

Same shared math as the NFL model (src/services/team_model.py) with the two
college-specific pieces from published college ratings (SP+, FPI, the
538/nfelo lineage): offseason reversion toward each program's long-run level
(an EWMA of its end-of-season ratings) instead of toward average, and a low
starting rating for teams first seen (overwhelmingly FCS opponents).

Data: ESPN FBS games with median closing spread/total across providers
(scripts/fetch_ncaaf_history.py). Fit 2016-2020, test 2021-2025, walk-forward.

Usage: python -m scripts.research_ncaaf_model --games ncaaf_games.csv [--config config/ncaaf_team_model.json]
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

TRAIN, TEST, SERVING_FROM = range(2016, 2021), range(2021, 2026), 2016
sig = lambda v: 1 / (1 + math.exp(-v))
logit = lambda p: math.log(p / (1 - p))


def load(path):
    out = []
    for r in csv.DictReader(open(path)):
        if r["home_score"] == "" or r["away_score"] == "":
            continue
        out.append({"season": int(r["season"]), "home": r["home"], "away": r["away"], "neutral": r["neutral"] == "1",
                    "hp": float(r["home_score"]), "ap": float(r["away_score"]),
                    "spread": -float(r["spread_line"]) if r["spread_line"] else None,
                    "total": float(r["total_line"]) if r["total_line"] else None})
    return out


# ---- margin ----------------------------------------------------------------------------------
MARGIN = ["k", "resist", "reversion", "hfa", "anchor_weight", "new_team"]
M_START = [0.8, 3.0, 0.4, 2.5, 0.5, -15.0]
m_to = lambda q: [math.exp(q[0]), math.exp(q[1]), sig(q[2]), q[3], sig(q[4]), q[5]]
m_from = lambda x: [math.log(x[0]), math.log(x[1]), logit(x[2]), x[3], logit(x[4]), x[5]]


def margins(games, x, state=None):
    k, resist, reversion, hfa, anchor_w, new_team = x
    p = tm.Params(k=k, resist=resist, reversion=reversion, hfa=hfa)
    R, anchors, season, preds = {}, {}, None, []
    for g in games:
        if g["season"] != season:
            if season is not None:
                anchors = tm.update_anchors(anchors, R, anchor_w)
            season, R = g["season"], tm.rollover(p, R, anchors)
        h, a = R.get(g["home"], new_team), R.get(g["away"], new_team)
        m = tm.expected_margin(p, h, a, neutral=g["neutral"])
        preds.append(m)
        R[g["home"]], R[g["away"]] = tm.update(p, h, a, m, g["hp"] - g["ap"], g["spread"])
    if state is not None:
        state.update({"ratings": R, "anchors": tm.update_anchors(anchors, R, anchor_w)})
    return np.array(preds)


def serving_elo(games):
    R, preds = {}, []
    for g in games:
        h, a = R.get(g["home"], 1500.0), R.get(g["away"], 1500.0)
        hfa = 0 if g["neutral"] else 65
        prob = 1 / (1 + 10 ** ((a - h - hfa) / 400))
        preds.append(((h + hfa - a) / 25.0, prob))
        y = 1.0 if g["hp"] > g["ap"] else 0.0 if g["hp"] < g["ap"] else 0.5
        R[g["home"]], R[g["away"]] = h + 20 * (y - prob), a - 20 * (y - prob)
    return preds


# ---- scoring ---------------------------------------------------------------------------------
SCORING = ["k", "resist", "reversion", "league_alpha", "hfa", "new_off", "new_def"]
S_START = [0.6, 4.0, 0.4, 0.002, 2.5, -6.0, -6.0]
s_to = lambda q: [math.exp(q[0]), math.exp(q[1]), sig(q[2]), sig(q[3]), q[4], q[5], q[6]]
s_from = lambda x: [math.log(x[0]), math.log(x[1]), logit(x[2]), logit(x[3]), x[4], x[5], x[6]]


def scoring(games, x, state=None):
    k, resist, reversion, alpha, hfa, new_off, new_def = x
    s = tm.ScoringParams(k=k, resist=resist, reversion=reversion, league_alpha=alpha, hfa=hfa)
    ratings, league, season, preds = {}, 28.0, None, []
    for g in games:
        if g["season"] != season:
            season, ratings = g["season"], tm.rollover_scoring(s, ratings)
        for t in (g["home"], g["away"]):
            ratings.setdefault(t, [new_off, new_def])
        oh, dh = ratings[g["home"]]
        oa, da = ratings[g["away"]]
        exp = tm.expected_points(s, league, oh, dh, oa, da, neutral=g["neutral"])
        preds.append(exp)
        league = tm.update_scoring(s, ratings, g["home"], g["away"], league, exp, (g["hp"], g["ap"]), g["total"])
    if state is not None:
        state.update({"ratings": ratings, "league": league})
    return np.array(preds)


def regress(model, market, floor, mid, steep):
    p = tm.Params(mr_floor=floor, mr_mid=mid, mr_steep=steep)
    return np.array([tm.regress_to_market(p, m, k) for m, k in zip(model, market)])


def fit_regression(raw, market, y, idx):
    have = [i for i in idx if market[i] is not None]
    shape = lambda q: (sig(q[0]), q[1], math.exp(q[2]))
    res = minimize(lambda q: float(np.mean((y[have] - regress(raw[have], [market[i] for i in have], *shape(q))) ** 2)),
                   [1.5, 3.0, 0.0], method="Nelder-Mead", options={"maxiter": 500})
    return shape(res.x)


def metrics(pred, prob, y, idx):
    yy, pp, pr = y[idx], pred[idx], prob[idx]
    won, keep = (yy > 0).astype(float), yy != 0
    return {"n": int(len(idx)), "mae": round(float(np.mean(np.abs(yy - pp))), 3),
            "brier": round(float(np.mean((pr[keep] - won[keep]) ** 2)), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", required=True)
    ap.add_argument("--config")
    args = ap.parse_args()
    games = load(args.games)
    seasons = np.array([g["season"] for g in games])
    y = np.array([g["hp"] - g["ap"] for g in games])
    sides = np.array([[g["hp"], g["ap"]] for g in games])
    totals = sides.sum(1)
    spread = [g["spread"] for g in games]
    tline = [g["total"] for g in games]
    train = np.where(np.isin(seasons, list(TRAIN)))[0]
    test = np.where(np.isin(seasons, list(TEST)))[0]
    lined = np.array([i for i in test if spread[i] is not None])

    def fit_all(idx):
        mres = minimize(lambda q: float(np.mean((y[idx] - margins(games, m_to(q))[idx]) ** 2)), m_from(M_START),
                        method="Nelder-Mead", options={"maxiter": 1500, "xatol": 1e-4, "fatol": 1e-6})
        mx = m_to(mres.x)
        raw = margins(games, mx)
        mreg = fit_regression(raw, spread, y, idx)
        final = np.array([raw[i] if spread[i] is None else regress([raw[i]], [spread[i]], *mreg)[0] for i in range(len(games))])
        sigma = float(np.sqrt(np.mean((y[idx] - final[idx]) ** 2)))
        sres = minimize(lambda q: float(np.mean((sides[idx] - scoring(games, s_to(q))[idx]) ** 2)), s_from(S_START),
                        method="Nelder-Mead", options={"maxiter": 2000, "xatol": 1e-4, "fatol": 1e-6})
        sx = s_to(sres.x)
        sraw = scoring(games, sx).sum(1)
        tsig = float(np.sqrt(np.mean((totals[idx] - sraw[idx]) ** 2)))
        return mx, mreg, sigma, raw, final, sx, sraw, tsig

    mx, mreg, sigma, raw, final, sx, sraw, tsig = fit_all(train)
    serve = serving_elo(games)
    smargin = np.array([s[0] for s in serve])
    sprob = np.array([s[1] for s in serve])
    market = np.array([s if s is not None else np.nan for s in spread])
    prob = lambda m: norm.cdf(m / sigma)
    t_lined = np.array([i for i in test if tline[i] is not None])
    report = {
        "train": [2016, 2020], "test": [2021, 2025], "games": len(games),
        "margin_params": dict(zip(MARGIN, map(lambda v: round(float(v), 4), mx))), "sigma": round(sigma, 3),
        "regression": dict(zip(["floor", "mid", "steep"], map(lambda v: round(float(v), 3), mreg))),
        "test_margin_lined_games": {
            "serving_elo": metrics(smargin, sprob, y, lined), "rebuilt_raw": metrics(raw, prob(raw), y, lined),
            "market_close": metrics(market, prob(market), y, lined), "rebuilt_regressed": metrics(final, prob(final), y, lined)},
        "scoring_params": dict(zip(SCORING, map(lambda v: round(float(v), 4), sx))), "total_sigma": round(tsig, 3),
        "test_total_mae": {"rebuilt_raw": round(float(np.mean(np.abs(totals[t_lined] - sraw[t_lined]))), 3),
                           "market_close": round(float(np.mean(np.abs(totals[t_lined] - np.array([tline[i] for i in t_lined])))), 3)},
    }
    print(json.dumps(report, indent=1))
    if args.config:
        mx, mreg, sigma, _, _, sx, _, tsig = fit_all(np.where(seasons >= SERVING_FROM)[0])
        mstate, sstate = {}, {}
        margins(games, mx, mstate)
        scoring(games, sx, sstate)
        artifact = {
            "recipe": "ncaaf_team_model_v1", "sport": "ncaaf", "team_key": "espn_id", "fitted_on": [SERVING_FROM, int(seasons.max())],
            "ratings_through_season": int(seasons.max()),
            "params": {"k": mx[0], "resist": mx[1], "reversion": mx[2], "hfa": mx[3], "rest": 0.0, "sigma": sigma,
                       "mr_floor": mreg[0], "mr_mid": mreg[1], "mr_steep": min(mreg[2], 50.0)},
            "anchor_weight": mx[4], "new_team_rating": mx[5],
            "ratings": {t: round(float(v), 3) for t, v in sorted(mstate["ratings"].items())},
            "anchors": {t: round(float(v), 3) for t, v in sorted(mstate["anchors"].items())},
            "scoring": {"params": {"k": sx[0], "resist": sx[1], "reversion": sx[2], "league_alpha": sx[3], "hfa": sx[4],
                                   "total_sigma": tsig, "mr_floor": 1.0, "mr_mid": 0.0, "mr_steep": 1.0},
                        "new_team": [sx[5], sx[6]], "league": round(sstate["league"], 3),
                        "ratings": {t: [round(o, 3), round(d, 3)] for t, (o, d) in sorted(sstate["ratings"].items())}},
            "evidence": {k: report[k] for k in ("train", "test", "test_margin_lined_games", "test_total_mae")},
            "sources": ["ESPN public scoreboard and odds APIs (FBS, 2016-2025)", "FiveThirtyEight/nfelo methods",
                        "SP+/FPI practice: preseason priors anchored to program level"]}
        json.dump(artifact, open(args.config, "w"), indent=2)


if __name__ == "__main__":
    main()
