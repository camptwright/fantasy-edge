"""Trade finder: one-for-one trades that improve BOTH starting lineups.

FantasyPros' Trade Finder looks for "trades your league-mates will accept".
Here a trade qualifies only when, over every remaining week with engine
research, your best offensive lineup gains points AND the other team's does
too (re-solved each week with and without the swap; byes count as zero).
Ranked by the smaller of the two gains, so the top rows help both sides most.

Research only: nothing is proposed or submitted. Runs in the background
(from the checkpoint read model) because it re-solves thousands of lineups.
"""

from __future__ import annotations

from src.services.fantasy_decision_models import FLEX, RESERVE
from src.services.waiver_guidance import OFFENSE, _research, lineup_total

MAX_CANDIDATES = 30   # other-roster players that would help your lineup, by added value
MAX_PER_GIVE = 2      # keep the list varied
LIMIT = 10


def _offense(players):
    return [p for p in players if p.get("position") in OFFENSE or not p.get("position")]


def find(data: dict, *, limit: int = LIMIT) -> dict:
    by_id = {str(p["player_id"]): p for p in data.get("players", [])}
    rosters = data.get("rosters", [])
    mine = [r for r in rosters if r.get("is_mine") is True]
    slots = [s for s in data.get("roster_positions", []) if s not in RESERVE and FLEX.get(s, {s}) <= OFFENSE]
    if len(mine) != 1 or not slots:
        return {"status": "owner_roster_unresolved" if len(mine) != 1 else "no_offensive_slots", "rows": []}
    members = {r["roster_id"]: [by_id[pid] for pid in map(str, r.get("player_ids", [])) if pid in by_id] for r in rosters}
    mine_id = mine[0]["roster_id"]
    if any(pid not in by_id for pid in map(str, mine[0].get('player_ids', []))):
        return {'status': 'incomplete_coverage', 'rows': []}
    weeks = sorted({w["week"] for p in members[mine_id] if _research(p) for w in p["engine"].get("weeks", [])})
    if not weeks:
        return {"status": "insufficient_engine_research", "rows": []}
    base = {rid: {w: lineup_total(_offense(ps), slots, w) for w in weeks} for rid, ps in members.items()}
    if any(v is None for v in base[mine_id].values()):
        return {'status': 'incomplete_coverage', 'weeks': weeks, 'rows': []}

    def gain(rid, give, get):
        after = [p for p in _offense(members[rid]) if p is not give] + [get]
        values = [lineup_total(after, slots, w) for w in weeks]
        if any(v is None for v in values) or any(v is None for v in base[rid].values()):
            return None
        return round(sum(v - base[rid][w] for w, v in zip(weeks, values)), 2)

    owner = {str(p["player_id"]): rid for rid, ps in members.items() for p in ps}
    # IR/taxi players (router-attached '_protected') are never offered.
    protected = data.get("_protected") or {}
    my_offense = [p for p in _offense(members[mine_id]) if _research(p) and str(p["player_id"]) not in protected]
    # Players elsewhere who would improve your lineup even as a pure addition.
    added = []
    for rid, ps in members.items():
        if rid == mine_id:
            continue
        roster = next(r for r in rosters if r['roster_id'] == rid)
        if any(pid not in by_id for pid in map(str, roster.get('player_ids', []))):
            continue
        if any(v is None for v in base[rid].values()):
            continue
        for p in _offense(ps):
            if _research(p):
                totals = [lineup_total(_offense(members[mine_id]) + [p], slots, w) for w in weeks]
                if any(v is None for v in totals):
                    continue
                value = round(sum(v - base[mine_id][w] for w, v in zip(weeks, totals)), 2)
                if value > 0:
                    added.append((value, p))
    added.sort(key=lambda t: (-t[0], str(t[1]["player_id"])))
    rows, per_give = [], {}
    for _, get in added[:MAX_CANDIDATES]:
        theirs = owner[str(get["player_id"])]
        for give in my_offense:
            mine_gain = gain(mine_id, give, get)
            if mine_gain is None or mine_gain <= 0:
                continue
            their_gain = gain(theirs, get, give)
            if their_gain is None or their_gain <= 0:
                continue
            rows.append({"give_id": str(give["player_id"]), "get_id": str(get["player_id"]), "partner_roster_id": theirs,
                         "my_gain": mine_gain, "their_gain": their_gain, "weeks": len(weeks)})
    rows.sort(key=lambda r: (-min(r["my_gain"], r["their_gain"]), -r["my_gain"], r["give_id"], r["get_id"]))
    out = []
    for r in rows:
        if per_give.get(r["give_id"], 0) >= MAX_PER_GIVE:
            continue
        per_give[r["give_id"]] = per_give.get(r["give_id"], 0) + 1
        out.append(r)
        if len(out) >= limit:
            break
    return {"status": "research", "weeks": weeks, "mutual_trades": len(rows), "rows": out}
