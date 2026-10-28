"""Correlated fantasy outcome simulation and the Sleeper/engine blend (E4 + E5).

Means. `blend_mean`: w_pos * engine + (1 - w_pos) * provider where both exist,
the provider alone otherwise (never the engine alone for a decision mean).
w_pos is fitted per position by `scripts/fit_fantasy_outcomes.py` on paired
retrospective engine/provider errors, shrunk toward 0 (the provider) by the
number of independent weeks.

Marginals. A player's score is mean + sd(mean) * z, with sd(mean) = a + b*mean
per position and z drawn from that position's empirical standardized-residual
quantiles (skew and bust mass come from data, not a normal assumption). Both
are fitted on frozen pre-kickoff provider projections graded on platform final
points.

Dependence. A Gaussian copula whose correlations depend only on the pair's
relation: same NFL team or opponents, by position pair (e.g. same:QB-WR,
opp:QB-QB). Fitted on nflverse 2025 player-game residuals. K/DEF have no
fitted pairs and are independent (stated assumption).

Known results: a player whose game is final enters with his recorded platform
points and no variance; any in-progress game withholds the simulation, since
no remaining-points model exists.

Everything here is research: the model file records its fit window and
out-of-sample checks, and nothing is promoted or submitted.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.stats import norm
from src.services.availability_status import ABSENT, normalize_status

MODEL_PATH = Path(__file__).resolve().parents[2] / "config" / "fantasy_outcome_model.json"
OFFENSE = ("QB", "RB", "WR", "TE")


@lru_cache(maxsize=1)
def load_model(path: str | None = None) -> dict | None:
    target = Path(path) if path else MODEL_PATH
    return json.loads(target.read_text()) if target.exists() else None


def blend_mean(position: str | None, provider: float | None, engine: float | None, model: dict) -> tuple[float | None, str]:
    if provider is None:
        return None, "missing_provider_projection"
    weight = model.get("blend_weights", {}).get(position or "", 0.0)
    if engine is None or weight <= 0:
        return provider, "provider"
    return weight * engine + (1 - weight) * provider, "blend"


def spread(position: str, mean: float, model: dict) -> tuple[float, np.ndarray, np.ndarray]:
    d = model["dispersion"].get(position) or model["dispersion"]["default"]
    sd = max(d["sd_min"], d["a"] + d["b"] * max(mean, 0.0))
    return sd, np.asarray(d["z_probs"], dtype=float), np.asarray(d["z_values"], dtype=float)


def pair_key(a: dict, b: dict) -> str | None:
    if not a.get("team") or not b.get("team"):
        return None
    if a["team"] == b["team"]:
        relation = "same"
    elif a.get("opponent") and a["opponent"] == b["team"]:
        relation = "opp"
    else:
        return None
    first, second = sorted((a["position"], b["position"]))
    return f"{relation}:{first}-{second}"


def correlation_matrix(players: list[dict], model: dict) -> np.ndarray:
    n = len(players)
    corr = np.eye(n)
    table = model.get("correlations", {})
    for i in range(n):
        for j in range(i + 1, n):
            key = pair_key(players[i], players[j])
            rho = table.get(key, {}).get("rho", 0.0) if key else 0.0
            corr[i, j] = corr[j, i] = rho
    # Pairwise estimates need not form a valid matrix: clip to the nearest PSD.
    values, vectors = np.linalg.eigh(corr)
    if values.min() < 1e-6:
        corr = vectors @ np.diag(np.clip(values, 1e-6, None)) @ vectors.T
        d = np.sqrt(np.diag(corr))
        corr = corr / np.outer(d, d)
    return corr


def simulate(players: list[dict], model: dict, *, draws: int = 10000, seed: int = 20261012,
             correlated: bool = True) -> dict[str, np.ndarray]:
    """players: dicts with player_id, position, team, opponent and either `mean` or `final_points`."""
    rng = np.random.default_rng(seed)
    live = [p for p in players if p.get("final_points") is None]
    out = {p["player_id"]: np.full(draws, float(p["final_points"])) for p in players if p.get("final_points") is not None}
    if not live:
        return out
    corr = correlation_matrix(live, model) if correlated else np.eye(len(live))
    normals = np.linalg.cholesky(corr) @ rng.standard_normal((len(live), draws))
    u = norm.cdf(normals)
    for p, row in zip(live, u):
        sd, probs, values = spread(p["position"], p["mean"], model)
        out[p["player_id"]] = p["mean"] + sd * np.interp(row, probs, values)
    return out


def matchup(mine: list[str], theirs: list[str], samples: dict[str, np.ndarray]) -> dict:
    a = sum(samples[pid] for pid in mine)
    b = sum(samples[pid] for pid in theirs)
    p = float(np.mean(a > b))
    return {"win_probability": p, "tie_probability": float(np.mean(a == b)),
            "monte_carlo_standard_error": float(np.sqrt(p * (1 - p) / len(a))),
            "mean": float(a.mean()), "opponent_mean": float(b.mean()),
            "p10": float(np.quantile(a, 0.1)), "p90": float(np.quantile(a, 0.9)),
            "opponent_p10": float(np.quantile(b, 0.1)), "opponent_p90": float(np.quantile(b, 0.9))}


DENSITY_EDGES = np.arange(-4.0, 52.0, 2.0)  # 2-point bins, -4 to 50 (tails clipped into end bins)


def player_range(samples: np.ndarray, boom: float, bust: float) -> dict:
    counts, _ = np.histogram(np.clip(samples, DENSITY_EDGES[0], DENSITY_EDGES[-1] - 1e-9), bins=DENSITY_EDGES)
    return {"density": [round(float(c), 4) for c in counts / counts.sum()],
            "p10": round(float(np.quantile(samples, 0.1)), 2), "p50": round(float(np.median(samples)), 2),
            "p90": round(float(np.quantile(samples, 0.9)), 2),
            "boom_probability": round(float(np.mean(samples >= boom)), 3),
            "bust_probability": round(float(np.mean(samples <= bust)), 3)}


# Position thresholds for boom/bust labels (points in the league's scoring).
BOOM_BUST = {"QB": (25.0, 12.0), "RB": (20.0, 6.0), "WR": (20.0, 6.0), "TE": (15.0, 4.0),
             "K": (12.0, 4.0), "DEF": (12.0, 2.0)}


def best_lineup(fixed: dict[int, str], open_slots: list[tuple[int, str]], pool: list[dict], opponent: list[str],
                players: list[dict], model: dict, *, draws: int = 10000, limit: int = 256) -> dict | None:
    """Max-win-probability lineup over unlocked slots with locked starters fixed.

    Candidates come from bounded legal-lineup enumeration (highest means first).
    The lineup is chosen on one half of the draws and its probability reported
    on the other half, so searching many lineups does not select noise.
    """
    from src.services.fantasy_simulation import legal_lineups
    slots = [s for _, s in open_slots]
    candidates, truncated = legal_lineups([{**p, "weekly_points": p.get("mean", p.get("final_points"))} for p in pool],
                                          slots, limit=limit)
    if not candidates:
        return None
    samples = simulate(players, model, draws=2 * draws)
    select, report = slice(0, draws), slice(draws, None)
    them = sum(samples[pid] for pid in opponent)

    def ids(candidate):
        out = dict(fixed)
        out.update({i: pid for (i, _), pid in zip(open_slots, candidate)})
        return [out[i] for i in sorted(out)]

    def win(lineup, part):
        mine = sum(samples[pid] for pid in lineup)
        return float(np.mean(mine[part] > them[part]))

    means = {p["player_id"]: p["mean"] for p in players if p.get("final_points") is None}
    means.update({p["player_id"]: p["final_points"] for p in players if p.get("final_points") is not None})
    chosen = max((ids(c) for c in candidates), key=lambda lineup: (win(lineup, select), sum(means[p] for p in lineup)))
    probability = win(chosen, report)
    return {"player_ids": chosen, "win_probability": probability,
            "monte_carlo_standard_error": float(np.sqrt(probability * (1 - probability) / draws)),
            "expected_points": round(sum(means[p] for p in chosen), 2),
            "candidates_evaluated": len(candidates), "search_truncated": truncated}


UNAVAILABLE = ABSENT


def lineup_changes(slots: list[str], current: list[str], best: list[str]) -> list[dict]:
    """Players the best lineup brings in, each paired with a starter it drops.

    Starters that only trade slots (RB <-> FLEX) are not a change, so a slot
    whose new player was already starting is skipped rather than reported as
    "start A over B; start B over A".
    """
    kept, starting = set(best), set(current)
    leaving = [pid for pid in current if pid not in kept]
    changes = []
    for i, pid in enumerate(best):
        if pid in starting:
            continue
        out = current[i] if current[i] in leaving else leaving[0]
        leaving.remove(out)
        changes.append({"slot": slots[i], "start": pid, "replaces": out})
    return changes


def _entry(p: dict, recorded: dict, now) -> tuple[dict | None, str | None]:
    """One player's simulation input, or a blocker. Never infers remaining points."""
    from datetime import datetime
    from src.services.roster_stat_model import finite
    pid = p["player_id"]
    base = {"player_id": pid, "position": p.get("position"), "team": p.get("nfl_team_id"),
            "opponent": p.get("nfl_opponent_id")}
    status, kickoff = p.get("week_game_status"), p.get("week_kickoff")
    if p.get("nfl_team_id") and status == "no_game_this_week":
        return {**base, "final_points": 0.0, "basis": "bye"}, None
    if status == "final":
        value = recorded.get(pid)
        return ({**base, "final_points": float(value), "basis": "final_recorded"}, None) if finite(value) \
            else (None, "final_without_recorded_points")
    if status is None or kickoff is None:
        return None, "unknown_game_binding"
    if datetime.fromisoformat(kickoff) <= now:
        return None, "game_in_progress"
    if p.get('game_availability', {}).get('hold_recommendation'):
        return None, 'event_availability_hold'
    if normalize_status(p.get("injury_status")) in UNAVAILABLE:
        return {**base, "final_points": 0.0, "basis": "designated_out"}, None
    model = load_model()
    provider = p.get("weekly_points") if p.get("weekly_evidence", {}).get("status") == "pregame_provider_projection" else None
    engine = (p.get("engine") or {}).get("week_points")
    mean, basis = blend_mean(p.get("position"), provider, engine, model)
    if mean is None or not finite(mean):
        return None, basis
    return {**base, "mean": float(mean), "basis": basis}, None


def research(by_id: dict, mine: list[str], theirs: list[str], roster: list[str], slots: list[str],
             recorded: dict, now, *, draws: int = 10000) -> dict:
    """Win probability now, the max-win-probability lineup, and player ranges. Research only."""
    from src.services.fantasy_decision_models import FLEX, RESERVE
    model = load_model()
    slots = [s for s in slots if s not in RESERVE]
    base = {"status": "withheld", "validated": False, "serving_promoted": False,
            "model": None if model is None else {k: model.get(k) for k in ("recipe", "fitted_at", "blend_status", "validation")},
            "assumptions": ["Gaussian copula; correlations by same-team/opponent position pair from nflverse 2025.",
                            "K/DEF independent; Questionable players assumed to play; Out/IR score zero.",
                            "Finished games use recorded platform points; started-but-unfinished games withhold the estimate."]}
    if model is None:
        return {**base, "reason": "outcome_model_not_fitted"}
    if not theirs or len(mine) != len(slots) or len(theirs) != len(slots):
        return {**base, "reason": "matchup_or_lineup_unbound"}
    entries, blockers = {}, []
    for pid in set(mine) | set(theirs):
        p = by_id.get(pid)
        entry, reason = _entry(p, recorded, now) if p else (None, "unknown_player")
        if reason:
            blockers.append({"player_id": pid, "name": (p or {}).get("name", pid), "reason": reason})
        else:
            entries[pid] = entry
    if blockers:
        return {**base, "reason": "starter_blockers", "blockers": sorted(blockers, key=lambda b: b["player_id"])}
    bench = []
    for pid in roster:
        if pid in entries or pid not in by_id:
            continue
        entry, reason = _entry(by_id[pid], recorded, now)
        if entry and entry.get("mean") is not None and not by_id[pid].get("locked", True):
            entries[pid] = entry
            bench.append(entry)
    players = list(entries.values())
    samples = simulate(players, model, draws=draws)
    current = matchup(mine, theirs, samples)
    # A bye or designated-out starter can still be benched; a started or
    # unbound game cannot.
    fixed = {i: pid for i, pid in enumerate(mine)
             if by_id[pid].get("locked", True) and entries[pid]["basis"] not in ("bye", "designated_out")}
    open_slots = [(i, s) for i, s in enumerate(slots) if i not in fixed]
    pool = [entries[pid] for i, pid in enumerate(mine) if i not in fixed] + bench
    best = best_lineup(fixed, open_slots, pool, theirs, players, model, draws=draws) if open_slots else None
    if best and all(entries[p]["position"] in FLEX.get(slots[i], {slots[i]}) for i, p in enumerate(best["player_ids"])):
        best["changes"] = lineup_changes(slots, mine, best["player_ids"])
    ranges = {}
    for pid, entry in entries.items():
        boom, bust = BOOM_BUST.get(entry["position"] or "", (20.0, 5.0))
        ranges[pid] = {**player_range(samples[pid], boom, bust), "basis": entry["basis"],
                       "mean": round(entry.get("mean", entry.get("final_points")), 2)}
    return {**base, "status": "estimated_research", "reason": "Unvalidated research simulation; not lineup advice.",
            "draws": draws, "current": current, "max_win_probability_lineup": best, "player_ranges": ranges,
            "known_final_starters": sum(e.get("final_points") is not None for pid, e in entries.items() if pid in set(mine) | set(theirs))}
