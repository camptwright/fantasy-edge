"""Standings and playoff odds by simulating the rest of the regular season.

FantasyPros' dashboard shows playoff odds; this is the transparent version:
- standings from completed weeks' matchup results (both platforms);
- each team's weekly score ~ Normal(points per game so far, league weekly
  spread), scaled week by week by the engine's projected starting lineup
  for that week relative to its average (so a bye-heavy week dips);
- remaining pairings from the stored schedule; 10,000 seasons; playoff
  seeds by wins, then points for.

Research: no league-specific tiebreakers beyond points for, no divisions.
"""

from __future__ import annotations

import numpy as np

SIMS = 10000
MIN_SD = 15.0


def standings(results: list[dict]) -> dict:
    """results: [{week, roster_id, matchup_id, points}] for completed weeks."""
    table: dict = {}
    by_game: dict = {}
    for r in results:
        by_game.setdefault((r["week"], r["matchup_id"]), []).append(r)
        t = table.setdefault(r["roster_id"], {"wins": 0, "losses": 0, "ties": 0, "pf": 0.0, "pa": 0.0, "games": 0})
        t["pf"] += r["points"]
        t["games"] += 1
    for game in by_game.values():
        if len(game) != 2:
            continue
        a, b = game
        table[a["roster_id"]]["pa"] += b["points"]
        table[b["roster_id"]]["pa"] += a["points"]
        if a["points"] == b["points"]:
            table[a["roster_id"]]["ties"] += 1
            table[b["roster_id"]]["ties"] += 1
        else:
            win, lose = (a, b) if a["points"] > b["points"] else (b, a)
            table[win["roster_id"]]["wins"] += 1
            table[lose["roster_id"]]["losses"] += 1
    return table


def simulate(table: dict, remaining: list[tuple[int, int, int]], strength: dict, playoff_teams: int,
             *, sd: float, sims: int = SIMS, seed: int = 11) -> dict:
    """remaining: [(week, roster_a, roster_b)]; strength: {(roster, week): mean points}."""
    teams = sorted(table)
    index = {t: i for i, t in enumerate(teams)}
    rng = np.random.default_rng(seed)
    wins = np.tile(np.array([table[t]["wins"] + 0.5 * table[t]["ties"] for t in teams], float), (sims, 1))
    pf = np.tile(np.array([table[t]["pf"] for t in teams], float), (sims, 1))
    for week, a, b in remaining:
        if a not in index or b not in index:
            continue
        sa = rng.normal(strength[(a, week)], sd, sims)
        sb = rng.normal(strength[(b, week)], sd, sims)
        wins[:, index[a]] += sa > sb
        wins[:, index[b]] += sb > sa
        pf[:, index[a]] += sa
        pf[:, index[b]] += sb
    # Seed by wins, then points for (a tiny pf weight breaks ties only).
    order = np.argsort(-(wins + pf * 1e-6), axis=1)
    made = np.zeros((sims, len(teams)), bool)
    np.put_along_axis(made, order[:, :playoff_teams], True, axis=1)
    top = np.zeros((sims, len(teams)), bool)
    np.put_along_axis(top, order[:, :1], True, axis=1)
    return {t: {"playoff_odds": round(float(made[:, i].mean()), 4), "first_seed_odds": round(float(top[:, i].mean()), 4),
                "projected_wins": round(float(wins[:, i].mean()), 2)} for t, i in index.items()}


def weekly_strength(table: dict, weeks: list[int], lineup: dict | None = None, clip: tuple[float, float] = (0.75, 1.25)) -> dict:
    """{(roster, week): mean} = points per game x (engine lineup that week / its average), clipped."""
    out = {}
    for team, t in table.items():
        ppg = t["pf"] / t["games"] if t["games"] else 0.0
        proj = {w: (lineup or {}).get((team, w)) for w in weeks}
        known = [v for v in proj.values() if v]
        avg = sum(known) / len(known) if known else None
        for w in weeks:
            factor = min(clip[1], max(clip[0], proj[w] / avg)) if avg and proj[w] is not None else 1.0
            out[(team, w)] = ppg * factor
    return out
