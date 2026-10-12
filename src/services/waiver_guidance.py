"""Waiver guidance: marginal starting-lineup points of each add/drop over the remaining weeks.

Raw rest-of-season points overrate players who would sit on your bench (a
second QB in a one-QB league). Here, for every remaining week with engine
research, the optimal offensive lineup (QB/RB/WR/TE and flex slots) is solved
with and without the swap; the guidance value is the summed lineup gain. A
player without a projection that week (bye, unavailable, unresolved) counts
as zero for that week, which is what a lineup would actually receive.

K/DEF are not engine-modeled: they get weekly streaming rows from the
provider projection only. Research only; nothing is submitted and the engine
is not prospectively qualified. Waiver bidding (FAAB) is out of scope.
"""

from __future__ import annotations

from src.services.fantasy_decision_models import FLEX, RESERVE, optimize
from src.services.roster_stat_model import finite

OFFENSE = {"QB", "RB", "WR", "TE"}
MAX_ADDS = 25
STREAM_LIMIT = 3  # top streaming options per K/DEF


def _research(p):
    return (p.get("engine") or {}).get("status") == "research"


def _week_points(p, week):
    if not _research(p):
        return 0.0
    return next((w["points"] for w in p["engine"].get("weeks", []) if w["week"] == week), 0.0)


def lineup_total(players, slots, week):
    rows = [{"player_id": p["player_id"], "name": p.get("name"), "position": p.get("position"),
             "weekly_points": _week_points(p, week)} for p in players]
    return optimize(rows, slots)["modeled_subtotal"]


def guidance(players: list[dict], mine: list[str], owned: set[str], roster_positions: list[str]) -> dict:
    by_id = {str(p["player_id"]): p for p in players}
    slots = [s for s in roster_positions if s not in RESERVE and FLEX.get(s, {s}) <= OFFENSE]
    roster = [by_id[pid] for pid in mine if pid in by_id]
    weeks = sorted({w["week"] for p in roster for w in (p.get("engine") or {}).get("weeks", [])} if roster else set())
    if not slots or not roster or not weeks:
        return {"status": "insufficient_engine_research", "rows": []}
    offense = [p for p in roster if p.get("position") in OFFENSE]
    base = {w: lineup_total(offense, slots, w) for w in weeks}
    pool = sorted((p for p in players if str(p["player_id"]) not in owned and p.get("roster_ids") == []
                   and p.get("position") in OFFENSE and _research(p)),
                  key=lambda p: (-(p["engine"].get("ros_points") or 0), str(p["player_id"])))[:MAX_ADDS]
    # Never drop a required kicker/defense; surplus ones are fair drops.
    surplus = [p for pos in ("K", "DEF")
               for p in sorted((q for q in roster if q.get("position") == pos),
                               key=lambda q: q.get("weekly_points") or 0)[:max(0, sum(q.get("position") == pos for q in roster)
                                                                               - roster_positions.count(pos))]]
    drops = offense + surplus
    rows = []
    for add in pool:
        best = None
        for drop in drops:
            after = [p for p in offense if p is not drop] + [add]
            gains = {w: round(lineup_total(after, slots, w) - base[w], 2) for w in weeks}
            total = round(sum(gains.values()), 2)
            key = (total, -((drop.get("engine") or {}).get("ros_points") or 0), str(drop["player_id"]))
            if best is None or key > best[0]:
                best = (key, drop, gains, total)
        _, drop, gains, total = best
        if total <= 0:
            continue
        # "Next week" is the add's next projected game, not a week he cannot play.
        first = next((w for w in weeks if _week_points(add, w) > 0), weeks[0])
        rows.append({"add_id": str(add["player_id"]), "drop_id": str(drop["player_id"]), "lineup_gain": total,
                     "week": first, "week_gain": gains[first], "weeks_improved": sum(g > 0 for g in gains.values()),
                     "weeks": len(weeks), "drop_is_kicker_or_defense": drop.get("position") in ("K", "DEF")})
    # K/DEF streaming: the provider's weekly projection only.
    for pos in ("K", "DEF"):
        current = [p for p in roster if p.get("position") == pos and finite(p.get("weekly_points"))]
        if not current:
            continue
        worst = min(current, key=lambda p: p["weekly_points"])
        candidates = sorted((p for p in players if str(p["player_id"]) not in owned and p.get("roster_ids") == []
                             and p.get("position") == pos and finite(p.get("weekly_points"))),
                            key=lambda p: (-p["weekly_points"], str(p["player_id"])))[:STREAM_LIMIT]
        for add in candidates:
            gain = round(add["weekly_points"] - worst["weekly_points"], 2)
            if gain > 0:
                rows.append({"add_id": str(add["player_id"]), "drop_id": str(worst["player_id"]), "lineup_gain": None,
                             "week": None, "week_gain": gain, "stream": True})
    return {"status": "research", "weeks": weeks, "slots": slots, "rows": rows}
