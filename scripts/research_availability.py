"""How often do designated players actually play? (Phase 3: participation probability.)

nflverse weekly injury reports (final game status + last practice status per
player-week) joined to PFR snap counts: a player "played" if he logged an
offensive snap in that week's game. Skill positions only (QB/RB/WR/TE).

Models, fitted on 2016-2023 and scored on 2024-2025:
- serving rule: Questionable plays, Doubtful/Out do not (what lineups assume);
- status: P(played | game status), pooled;
- status x practice: P(played | game status, last practice participation);
- status x practice x position, shrunk toward status x practice (k pseudo-games).

Only regulars count: a player whose offensive snap share averaged at least
REGULAR_SHARE over his previous REGULAR_GAMES games that season. Without this,
healthy backups who were active but never took a snap (most "Questionable"
quarterbacks) read as "did not play" and the rates measure depth, not health.

Writes config/availability_rates.json with the chosen table and evidence.
Run in the worker environment: python -m scripts.research_availability
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.ingest.nflverse import _nflreadpy, _records

FIT = range(2016, 2024)
TEST = (2024, 2025)
POSITIONS = {"QB", "RB", "WR", "TE"}
PRACTICE = {"Did Not Participate In Practice": "dnp", "Limited Participation in Practice": "limited",
            "Full Participation in Practice": "full"}
STATUSES = {"Questionable", "Doubtful", "Out"}
SHRINK = 40
REGULAR_SHARE = 0.4
REGULAR_GAMES = 3
OUT = Path(__file__).resolve().parents[1] / "config" / "availability_rates.json"


def rows(seasons):
    nfl = _nflreadpy()
    injuries = _records(nfl.load_injuries(list(seasons)))
    snaps = _records(nfl.load_snap_counts(list(seasons)))
    players = _records(nfl.load_players())
    gsis_by_pfr = {p["pfr_id"]: p["gsis_id"] for p in players if p.get("pfr_id") and p.get("gsis_id")}
    share = defaultdict(dict)  # (season, gsis) -> {week: offense pct}
    for s in snaps:
        gsis = gsis_by_pfr.get(s.get("pfr_player_id"))
        if gsis and s.get("game_type") == "REG":
            share[(int(s["season"]), gsis)][int(s["week"])] = float(s.get("offense_pct") or 0.0)
    weeks_with_snaps = {(int(s["season"]), int(s["week"]), s.get("team")) for s in snaps}
    out = []
    for r in injuries:
        status = r.get("report_status")
        if (r.get("game_type") != "REG" or r.get("position") not in POSITIONS or status not in STATUSES
                or not r.get("gsis_id") or (int(r["season"]), int(r["week"]), r.get("team")) not in weeks_with_snaps):
            continue
        season, week = int(r["season"]), int(r["week"])
        history = share.get((season, r["gsis_id"]), {})
        prior = [history[w] for w in sorted(history) if w < week][-REGULAR_GAMES:]
        if len(prior) < REGULAR_GAMES or sum(prior) / len(prior) < REGULAR_SHARE:
            continue
        out.append({"season": season, "week": week, "position": r["position"], "status": status,
                    "practice": PRACTICE.get(r.get("practice_status"), "unknown"),
                    "played": history.get(week, 0.0) > 0})
    return out


def table(data, keys):
    counts = defaultdict(lambda: [0, 0])
    for r in data:
        c = counts[tuple(r[k] for k in keys)]
        c[0] += r["played"]
        c[1] += 1
    return {k: (p, n) for k, (p, n) in counts.items()}


def brier(pred, data):
    p = np.array(pred, float)
    y = np.array([r["played"] for r in data], float)
    return round(float(np.mean((p - y) ** 2)), 4)


def main():
    fit, test = rows(FIT), rows(TEST)
    status = table(fit, ("status",))
    practice = table(fit, ("status", "practice"))
    positional = table(fit, ("status", "practice", "position"))

    def rate(t, key, fallback=None):
        p, n = t.get(key, (0, 0))
        return p / n if n else fallback

    def p_status(r):
        return rate(status, (r["status"],))

    def p_practice(r):
        return rate(practice, (r["status"], r["practice"]), p_status(r))

    def p_position(r):
        prior = p_practice(r)
        p, n = positional.get((r["status"], r["practice"], r["position"]), (0, 0))
        return (p + SHRINK * prior) / (n + SHRINK)

    models = {"serving_rule": lambda r: 1.0 if r["status"] == "Questionable" else 0.0,
              "status": p_status, "status_practice": p_practice, "status_practice_position": p_position}
    evidence = {name: {"brier": brier([m(r) for r in test], test)} for name, m in models.items()}
    for name, m in models.items():
        by = defaultdict(list)
        for r in test:
            by[r["status"]].append((m(r), r["played"]))
        evidence[name]["by_status"] = {s: {"n": len(v), "predicted": round(float(np.mean([a for a, _ in v])), 3),
                                           "played": round(float(np.mean([b for _, b in v])), 3)} for s, v in sorted(by.items())}
    best = min(("status", "status_practice", "status_practice_position"), key=lambda k: evidence[k]["brier"])
    # Refit the chosen table on every season so serving uses all the history.
    full = fit + test
    final = {"status": table(full, ("status",)), "status_practice": table(full, ("status", "practice")),
             "status_practice_position": table(full, ("status", "practice", "position"))}
    artifact = {"recipe": "availability_rates_v1", "chosen": best, "fitted_on": f"{FIT.start}-{TEST[-1]} REG",
                "generated_at": datetime.now(timezone.utc).isoformat(), "shrink": SHRINK,
                "played_definition": "logged an offensive snap (PFR snap counts)",
                "population": f"regulars: >= {REGULAR_SHARE:.0%} offensive snaps over the previous {REGULAR_GAMES} games",
                "tables": {name: {"|".join(k): {"played": p, "n": n} for k, (p, n) in sorted(t.items())}
                           for name, t in final.items()},
                "evidence": {"fit_seasons": [FIT.start, FIT.stop - 1], "test_seasons": list(TEST),
                             "fit_rows": len(fit), "test_rows": len(test), "models": evidence}}
    OUT.write_text(json.dumps(artifact, indent=1) + "\n")
    print(json.dumps({"chosen": best, **artifact["evidence"]}, indent=1))


if __name__ == "__main__":
    main()
