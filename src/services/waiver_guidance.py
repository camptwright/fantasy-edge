"""Waiver guidance: marginal starting-lineup points of each add/drop over the remaining weeks.

Raw rest-of-season points overrate players who would sit on your bench (a
second QB in a one-QB league). Here, for every remaining week with engine
research, the optimal offensive lineup (QB/RB/WR/TE and flex slots) is solved
with and without the swap; the guidance value is the summed lineup gain. A
missing projection withholds comparison. Only verified byes and confirmed
absence receive zero. Planning is bounded to two to four weeks.

K/DEF are not engine-modeled: they get weekly streaming rows from the
provider projection only. Research only; nothing is submitted and the engine
is not prospectively qualified. Waiver bidding (FAAB) is out of scope.
"""

from __future__ import annotations

from src.services.fantasy_decision_models import FLEX, RESERVE
from src.services.roster_stat_model import finite
from src.services.engine_coverage import week_state, solve, horizon

OFFENSE = {"QB", "RB", "WR", "TE"}
MAX_ADDS = 25
STREAM_LIMIT = 3  # top streaming options per K/DEF


def _research(p):
    return (p.get("engine") or {}).get("status") == "research"


def _week_points(p, week):
    return week_state(p, week)['points']


def lineup_total(players, slots, week):
    return solve(players, slots, week)['total']


def _stream_eligible(player, week):
    if not finite(player.get('weekly_points')):
        return False
    evidence = player.get('weekly_evidence')
    if evidence and (evidence.get('status') != 'pregame_provider_projection' or evidence.get('week') != week):
        return False
    return week_state(player, week)['status'] not in ('verified_bye', 'confirmed_unavailable')


def guidance(players: list[dict], mine: list[str], owned: set[str], roster_positions: list[str], *,
             start_week=None, horizon_weeks=2, min_lineup_gain=1.0, min_stream_gain=1.0) -> dict:
    if not finite(min_lineup_gain) or min_lineup_gain < 0 or not finite(min_stream_gain) or min_stream_gain < 0:
        raise ValueError('gain thresholds must be finite and nonnegative')
    by_id = {str(p["player_id"]): p for p in players}
    unknown_ids = [str(pid) for pid in mine if str(pid) not in by_id]
    if unknown_ids:
        return {'status': 'incomplete_coverage', 'rows': [],
                'coverage_blockers': [{'week': start_week, 'missing_player_ids': unknown_ids}]}
    slots = [s for s in roster_positions if s not in RESERVE and FLEX.get(s, {s}) <= OFFENSE]
    roster = [by_id[str(pid)] for pid in mine if str(pid) in by_id]
    weeks = horizon(roster, start_week, horizon_weeks)
    if not slots or not roster or not weeks:
        return {"status": "insufficient_engine_research", "rows": []}
    # An unresolved position might occupy an offensive slot; it is not a known specialist to omit.
    offense = [p for p in roster if p.get("position") in OFFENSE or not p.get("position")]
    base = {w: lineup_total(offense, slots, w) for w in weeks}
    blockers = [{'week': w, 'missing_player_ids': solve(offense, slots, w)['missing_player_ids']}
                for w in weeks if base[w] is None]
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
    for add in pool if not blockers else []:
        best = None
        alternatives = []
        for drop in drops:
            after = [p for p in offense if p is not drop] + [add]
            after_totals = {w: lineup_total(after, slots, w) for w in weeks}
            if any(v is None for v in after_totals.values()):
                continue
            gains = {w: round(after_totals[w] - base[w], 2) for w in weeks}
            total = round(sum(gains.values()), 2)
            alternatives.append({'drop_id': str(drop['player_id']), 'lineup_gain': total,
                                 'weekly': [{'week': w, 'gain': gains[w]} for w in weeks]})
            key = (total, -((drop.get("engine") or {}).get("ros_points") or 0), str(drop["player_id"]))
            if best is None or key > best[0]:
                best = (key, drop, gains, total)
        if best is None:
            continue
        _, drop, gains, total = best
        if total <= 0 or total < min_lineup_gain:
            continue
        # Report immediate impact even when the pickup helps a later bye week.
        first = weeks[0]
        needed = next((w for w in weeks if gains[w] > 0), None)
        events = [g for g in add.get('next_games', []) if g.get('week') == needed and g.get('kickoff')]
        rows.append({"add_id": str(add["player_id"]), "drop_id": str(drop["player_id"]), "lineup_gain": total,
                     "week": first, "week_gain": gains[first], "weeks_improved": sum(g > 0 for g in gains.values()),
                     "weeks": len(weeks), "drop_is_kicker_or_defense": drop.get("position") in ("K", "DEF"),
                     'weekly': [{'week': w, 'gain': gains[w], 'add_status': week_state(add, w)['status']} for w in weeks],
                     'alternative_drops': sorted(alternatives, key=lambda r: (-r['lineup_gain'], r['drop_id']))[:5],
                     'needed_by_week': needed,
                     'target_game_kickoff': events[0]['kickoff'] if len(events) == 1 else None,
                     'claim_timing': 'check_league_waiver_deadline_before_target_game'})
    # K/DEF streaming: the provider's weekly projection only.
    for pos in ("K", "DEF"):
        current = [p for p in roster if p.get("position") == pos and _stream_eligible(p, weeks[0])]
        if not current:
            continue
        worst = min(current, key=lambda p: p["weekly_points"])
        candidates = sorted((p for p in players if str(p["player_id"]) not in owned and p.get("roster_ids") == []
                             and p.get("position") == pos and _stream_eligible(p, weeks[0])),
                            key=lambda p: (-p["weekly_points"], str(p["player_id"])))[:STREAM_LIMIT]
        for add in candidates:
            gain = round(add["weekly_points"] - worst["weekly_points"], 2)
            if gain > 0 and gain >= min_stream_gain:
                rows.append({"add_id": str(add["player_id"]), "drop_id": str(worst["player_id"]), "lineup_gain": None,
                             "week": None, "week_gain": gain, "stream": True})
    return {"status": "incomplete_coverage" if blockers else "research", "weeks": weeks, "slots": slots, "rows": rows,
            'coverage_blockers': blockers, 'horizon_weeks': horizon_weeks,
            'thresholds': {'min_lineup_gain': min_lineup_gain, 'min_stream_gain': min_stream_gain}}
