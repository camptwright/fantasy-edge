"""Trade outlook: rest-of-season starting-lineup impact of a trade, by position.

For each side, every remaining week with engine research is solved twice -
the roster before and after the trade (plus any explicit add/drop plan) - and
the lineup points are summed. The per-position split attributes each week's
lineup points to the starting player's own position, so a flex WR counts as WR.
This is what the WalterPicks-style position delta tiles show.

Request-time research only: it reads the saved checkpoint, is not part of the
versioned prediction, and never submits or recommends accepting a trade.
"""

from __future__ import annotations

from src.services.waiver_guidance import OFFENSE, _research, _week_points
from src.services.fantasy_decision_models import FLEX, RESERVE, optimize


def _solve(players, slots, week):
    rows = [{"player_id": p["player_id"], "name": p.get("name"), "position": p.get("position"),
             "weekly_points": _week_points(p, week)} for p in players]
    lineup = optimize(rows, slots)["lineup"]
    position = {str(p["player_id"]): p.get("position") for p in players}
    split = {pos: 0.0 for pos in sorted(OFFENSE)}
    for slot in lineup:
        if slot["player_id"] is not None:
            split[position[str(slot["player_id"])]] += slot["points"] or 0.0
    return split


def side_outlook(roster: list[dict], give: list[dict], receive: list[dict], roster_positions: list[str],
                 adds: list[dict] = (), drops: list[dict] = ()) -> dict:
    slots = [s for s in roster_positions if s not in RESERVE and FLEX.get(s, {s}) <= OFFENSE]
    gone = {str(p["player_id"]) for p in [*give, *drops]}
    before = [p for p in roster if p.get("position") in OFFENSE]
    after = [p for p in [*roster, *receive, *adds] if p.get("position") in OFFENSE and str(p["player_id"]) not in gone]
    weeks = sorted({w["week"] for p in before + after if _research(p) for w in p["engine"].get("weeks", [])})
    if not slots or not weeks:
        return {"status": "insufficient_engine_research"}
    by_position = {pos: 0.0 for pos in sorted(OFFENSE)}
    weekly = []
    for week in weeks:
        b, a = _solve(before, slots, week), _solve(after, slots, week)
        for pos in by_position:
            by_position[pos] += a[pos] - b[pos]
        weekly.append({"week": week, "gain": round(sum(a.values()) - sum(b.values()), 2)})
    # Players whose engine research is missing count as zero, so say so.
    unmodeled = [str(p["player_id"]) for p in [*give, *receive, *adds] if p.get("position") in OFFENSE and not _research(p)]
    return {"status": "research", "weeks": len(weeks), "lineup_gain": round(sum(w["gain"] for w in weekly), 2),
            "by_position": {k: round(v, 2) for k, v in by_position.items()}, "weekly": weekly,
            "unmodeled_player_ids": unmodeled}


def outlook(data: dict, side_a: list[str], side_b: list[str], plans: dict | None = None) -> dict:
    """Both sides' outlook from a checkpoint read model; withheld unless both rosters are known."""
    by_id = {str(p["player_id"]): p for p in data.get("players", [])}
    rosters = data.get("rosters", [])
    plans = plans or {}

    def owner(ids):
        found = {r["roster_id"] for r in rosters for pid in ids if pid in map(str, r.get("player_ids", []))}
        return next(r for r in rosters if r["roster_id"] in found) if len(found) == 1 else None

    ra, rb = owner(side_a), owner(side_b)
    if ra is None or rb is None or ra is rb or any(pid not in by_id for pid in side_a + side_b):
        return {"status": "rosters_unresolved"}
    sides = {}
    for key, roster, give, receive in (("side_a", ra, side_a, side_b), ("side_b", rb, side_b, side_a)):
        plan = plans.get(key[-1], {})
        members = [by_id[pid] for pid in map(str, roster.get("player_ids", [])) if pid in by_id]
        sides[key] = {"team": roster.get("name"), **side_outlook(
            members, [by_id[p] for p in give], [by_id[p] for p in receive], data.get("roster_positions") or [],
            [by_id[p] for p in plan.get("add", []) if p in by_id], [by_id[p] for p in plan.get("drop", []) if p in by_id])}
    values = {pid: (by_id[pid].get("engine") or {}).get("ros_points") if _research(by_id[pid]) else None
              for pid in side_a + side_b}
    return {"status": "research", **sides, "player_ros_points": values}
