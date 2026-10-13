"""Parlay generator: a local model reads the request, deterministic code builds and prices it.

Division of labour (the AI never chooses or prices a leg):
1. `interpret` (src/services/parlay_ai.py) turns free text into constraints
   (legs, mode, sides, teams, stats, players). Every extracted value is
   checked against the request text and the live slate; anything it cannot
   ground is dropped, so a hallucinated player or team does nothing.
2. `generate` builds the best parlay per book from the prop board. A parlay
   is placed at one book, so legs are that book's prices at the consensus
   main line; fair probabilities are the board's no-vig consensus.
3. Joint probability: independent across games; within a game a Gaussian
   copula over residual correlations measured on 2025 player-games
   (config/prop_correlations.json; on 2026 holdout pairs with |rho| >= 0.15 it
   beat independence, Brier 0.2004 vs 0.2087).

Modes: value maximises sum log(1 + EV) of the legs; safe maximises the joint
hit probability among legs with EV >= -2%; balanced mixes both. Correlation
is never scored as value: books reprice correlated same-game legs, so a
"lift" from stacking them is theirs, not ours. Named players are required
legs (the best-priced prop for each), not the only players allowed. For a parlay of
legs in different games the book pays the product of prices, so its EV is
exact given the fair probabilities. Same-game parlays are repriced by books
with their own correlation model, so only the fair odds (the price to beat)
are reported for them, never an EV.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.stats import norm

from src.utils.odds_math import american_to_decimal, decimal_to_american

CORRELATIONS = Path(__file__).resolve().parents[2] / "config" / "prop_correlations.json"
MODES = ("value", "balanced", "safe")
SIMS = 60000
POOL = 40  # candidates per book considered by the greedy search


@dataclass
class Constraints:
    legs: int = 3
    mode: str = "value"
    side: str = "any"            # any | over | under
    same_game: bool = False
    teams: list[str] = field(default_factory=list)
    stats: list[str] = field(default_factory=list)
    players: list[str] = field(default_factory=list)
    exclude_players: list[str] = field(default_factory=list)
    books: list[str] = field(default_factory=list)
    min_books: int = 3
    min_probability: float = 0.0

    def clean(self) -> "Constraints":
        self.legs = max(2, min(6, int(self.legs)))
        self.mode = self.mode if self.mode in MODES else "value"
        self.side = self.side if self.side in ("any", "over", "under") else "any"
        self.min_books = max(1, min(6, int(self.min_books)))
        self.min_probability = max(0.0, min(0.9, float(self.min_probability)))
        return self


@lru_cache(maxsize=1)
def correlations() -> dict:
    return json.loads(CORRELATIONS.read_text())["pairs"] if CORRELATIONS.exists() else {}


def legs_from_board(rows: list[dict]) -> list[dict]:
    """One leg per (row, side, book) at the row's main line, priced by that book, fair from the consensus."""
    out = []
    for r in rows:
        if r.get("fair_over") is None:
            continue
        for o in r["offers"]:
            if o["line"] != r["line"]:
                continue
            for side in ("over", "under"):
                price = o.get(side)
                if not isinstance(price, int) or abs(price) < 100:
                    continue
                fair = r["fair_over"] if side == "over" else 1 - r["fair_over"]
                hit = (r.get("hit") or {}).get("l10")
                out.append({"id": f"{r['key']}:{side}:{o['book']}", "row": r["key"], "book": o["book"], "price": price,
                            "fair": round(fair, 4), "ev": round(fair * american_to_decimal(price) - 1, 4),
                            "side": side, "line": r["line"], "stat": r["stat"], "player": r["player"],
                            "player_id": r["player_id"], "position": r.get("position"), "team": r.get("team"),
                            "opponent": r.get("opponent"), "game_id": r["game_id"], "game_time": r["game_time"],
                            "matchup": r["matchup"], "sport": r["sport"], "books": r["books"],
                            "hit_l10": hit, "dvp": r.get("dvp"), "engine": r.get("engine")})
    return out


def _matches(name: str, wanted: list[str]) -> bool:
    low = name.casefold()
    return any(w.casefold() in low for w in wanted)


def eligible(legs: list[dict], c: Constraints) -> list[dict]:
    out = []
    for leg in legs:
        if c.side != "any" and leg["side"] != c.side:
            continue
        if c.stats and leg["stat"] not in c.stats:
            continue
        if c.books and leg["book"] not in c.books:
            continue
        if c.teams and not ({leg["team"], leg["opponent"]} & set(c.teams)):
            continue
        if c.exclude_players and _matches(leg["player"], c.exclude_players):
            continue
        if leg["books"] < c.min_books or leg["fair"] < c.min_probability:
            continue
        if c.mode == "safe" and leg["ev"] < -0.02:
            continue
        out.append(leg)
    return out


def rho(a: dict, b: dict, table: dict | None = None) -> float:
    """Latent correlation between two legs' events (sign flips for unders)."""
    if a["game_id"] != b["game_id"]:
        return 0.0
    table = correlations() if table is None else table
    if a["player_id"] == b["player_id"]:
        relation = "same_player"
    elif a["team"] and b["team"]:
        relation = "teammate" if a["team"] == b["team"] else "opponent"
    else:
        return 0.0
    x, y = f"{a['position']}:{a['stat']}", f"{b['position']}:{b['stat']}"
    value = table.get(f"{relation}|{min(x, y)}|{max(x, y)}", {}).get("rho", 0.0)
    return value * (1 if a["side"] == b["side"] else -1)


def joint_probability(legs: list[dict], table: dict | None = None, *, sims: int = SIMS, seed: int = 7) -> float:
    """P(every leg hits). Exact product when legs are uncorrelated; Gaussian copula otherwise."""
    n = len(legs)
    corr = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            corr[i, j] = corr[j, i] = rho(legs[i], legs[j], table)
    p = np.array([leg["fair"] for leg in legs])
    if np.allclose(corr, np.eye(n)):
        return float(np.prod(p))
    values, vectors = np.linalg.eigh(corr)
    corr = vectors @ np.diag(np.clip(values, 1e-6, None)) @ vectors.T
    d = np.sqrt(np.diag(corr))
    corr = corr / np.outer(d, d)
    z = np.random.default_rng(seed).multivariate_normal(np.zeros(n), corr, size=sims, method="cholesky")
    return float(np.mean(np.all(z > norm.ppf(1 - p), axis=1)))


def objective(legs: list[dict], mode: str, joint: float) -> float:
    value = sum(math.log(max(1e-6, 1 + leg["ev"])) for leg in legs)
    if mode == "safe":
        return math.log(max(1e-9, joint))
    if mode == "balanced":
        return value + 0.5 * math.log(max(1e-9, joint))
    return value


def _compatible(leg: dict, chosen: list[dict], same_game: bool) -> bool:
    for other in chosen:
        if other["row"] == leg["row"]:
            return False  # one side of one prop
        if not same_game and other["game_id"] == leg["game_id"]:
            return False
    return True


def best_for_book(legs: list[dict], c: Constraints, table: dict | None = None) -> list[dict] | None:
    """Greedy: repeatedly add the leg that most improves the objective of the whole set."""
    key = {"value": lambda leg: -leg["ev"], "safe": lambda leg: -leg["fair"],
           "balanced": lambda leg: -(leg["ev"] + 0.5 * math.log(leg["fair"]))}[c.mode]
    ranked = sorted(legs, key=lambda leg: (key(leg), leg["id"]))
    chosen: list[dict] = []
    for name in c.players:  # required legs first: each named player's best prop at this book
        options = [leg for leg in ranked if _matches(leg["player"], [name]) and _compatible(leg, chosen, c.same_game)]
        if not options:
            return None
        chosen.append(options[0])
    pool = [leg for leg in ranked if not c.players or leg in chosen or not _matches(leg["player"], c.players)][:POOL] + chosen
    if len(chosen) > c.legs:
        return None
    while len(chosen) < c.legs:
        best, best_score = None, -math.inf
        for leg in pool:
            if leg in chosen or not _compatible(leg, chosen, c.same_game):
                continue
            trial = chosen + [leg]
            s = objective(trial, c.mode, joint_probability(trial, table, sims=8000))
            if s > best_score + 1e-12:
                best, best_score = leg, s
        if best is None:
            return None
        chosen.append(best)
    return chosen


def price(legs: list[dict], table: dict | None = None) -> dict:
    decimal = math.prod(american_to_decimal(leg["price"]) for leg in legs)
    independent = math.prod(leg["fair"] for leg in legs)
    joint = joint_probability(legs, table)
    same_game = len({leg["game_id"] for leg in legs}) < len(legs)
    return {"book": legs[0]["book"], "legs": [{**leg, "reasons": reasons(leg)} for leg in legs],
            "decimal": round(decimal, 3), "american": decimal_to_american(decimal),
            "independent_probability": round(independent, 4), "probability": round(joint, 4),
            "fair_american": decimal_to_american(1 / joint) if 0 < joint < 1 else None,
            "same_game": same_game,
            # Different games: the book pays the product, so EV follows from the fair probabilities.
            "ev": None if same_game else round(joint * decimal - 1, 4)}


def reasons(leg: dict) -> list[str]:
    out = [f"{leg['ev'] * 100:+.1f}% vs {leg['books']}-book no-vig consensus ({leg['fair'] * 100:.0f}% fair)"]
    hit = leg.get("hit_l10")
    if hit and hit["games"]:
        hits = hit["hits"] if leg["side"] == "over" else hit["games"] - hit["hits"]
        out.append(f"{leg['side']} hit {hits}/{hit['games']} last {hit['games']}")
    dvp = leg.get("dvp")
    if dvp and leg.get("opponent"):
        out.append(f"{leg['opponent']} ranks {dvp['rank']}/{dvp['teams']} allowing {leg['stat'].replace('_', ' ')} to {leg['position']}s")
    if leg.get("engine") and leg["stat"] in ("receptions", "receiving_yards", "rushing_yards"):
        p = leg["engine"]["over_probability"] if leg["side"] == "over" else 1 - leg["engine"]["over_probability"]
        out.append(f"engine projects {leg['engine']['projection']} ({p * 100:.0f}% {leg['side']}, research)")
    return out


def generate(rows: list[dict], c: Constraints, *, alternatives: int = 3, table: dict | None = None, relax: bool = True) -> dict:
    """Best parlay per book for the constraints. On a thin slate (too few games at one book) it retries
    allowing same-game legs and says so, rather than returning nothing."""
    c.clean()
    out = _generate(rows, c, alternatives, table)
    if relax and out["status"] == "constraints_unmet" and not c.same_game:
        retry = _generate(rows, Constraints(**{**c.__dict__, "same_game": True}).clean(), alternatives, table)
        if retry["parlays"]:
            return {**retry, "relaxed": "same_game"}
    return out


def _generate(rows: list[dict], c: Constraints, alternatives: int, table: dict | None) -> dict:
    legs = eligible(legs_from_board(rows), c)
    by_book: dict[str, list[dict]] = {}
    for leg in legs:
        by_book.setdefault(leg["book"], []).append(leg)
    built = []
    for book, book_legs in sorted(by_book.items()):
        chosen = best_for_book(book_legs, c, table)
        if chosen:
            priced = price(chosen, table)
            priced["score"] = round(objective(chosen, c.mode, priced["probability"]), 4)
            built.append(priced)
    built.sort(key=lambda p: (-p["score"], p["book"]))
    status = "built" if built else ("no_candidates" if not legs else "constraints_unmet")
    return {"status": status, "candidates": len(legs), "books": sorted(by_book), "parlays": built[:alternatives]}
