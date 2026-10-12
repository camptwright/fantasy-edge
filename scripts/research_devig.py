"""Which vig-removal method gives the best-calibrated fair probabilities?

Methods (as published by OddsJam/Unabated/the betting literature):
- multiplicative (proportional): p_i / sum(p)
- additive: p_i - (sum(p) - 1) / n
- power: find k with sum(p_i ** k) = 1
- Shin (1993): models insider trading; corrects the favourite-longshot bias.

Data: nflverse games.csv closing moneylines (home_moneyline/away_moneyline),
regular season and playoffs, decided games only. Scored by log loss and
Brier against the home result, overall and for big favourites.

Usage: python -m scripts.research_devig --games games.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math

import numpy as np
from scipy.optimize import brentq


def implied(american: float) -> float:
    return 100 / (american + 100) if american > 0 else -american / (-american + 100)


def multiplicative(p):
    return [x / sum(p) for x in p]


def additive(p):
    over = sum(p) - 1
    return [x - over / len(p) for x in p]


def power(p):
    k = brentq(lambda k: sum(x ** k for x in p) - 1, 0.5, 3.0)
    return [x ** k for x in p]


def shin(p):
    total = sum(p)
    n = len(p)

    def probs(z):
        return [(math.sqrt(z ** 2 + 4 * (1 - z) * x ** 2 / total) - z) / (2 * (1 - z)) for x in p]
    z = brentq(lambda z: sum(probs(z)) - 1, 0.0, 0.4) if total > 1 else 0.0
    return probs(z)


METHODS = {"multiplicative": multiplicative, "additive": additive, "power": power, "shin": shin}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", required=True)
    args = ap.parse_args()
    rows = []
    for r in csv.DictReader(open(args.games)):
        if r["result"] and r["home_moneyline"] and r["away_moneyline"] and float(r["result"]) != 0:
            rows.append((implied(float(r["home_moneyline"])), implied(float(r["away_moneyline"])), float(r["result"]) > 0))
    y = np.array([w for *_, w in rows], float)
    out = {"games": len(rows), "methods": {}}
    for name, f in METHODS.items():
        p = np.array([f([h, a])[0] for h, a, _ in rows])
        p = np.clip(p, 1e-6, 1 - 1e-6)
        fav = np.maximum(p, 1 - p) >= 0.75
        won_fav = np.where(p >= 0.5, y, 1 - y)
        out["methods"][name] = {
            "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 5),
            "brier": round(float(np.mean((p - y) ** 2)), 5),
            "big_favourites": {"n": int(fav.sum()), "mean_forecast": round(float(np.maximum(p, 1 - p)[fav].mean()), 4),
                               "win_rate": round(float(won_fav[fav].mean()), 4)}}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
