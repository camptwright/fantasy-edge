"""Trade value model and trade recommender.

Trade value is deliberately NOT a rest-of-season dynasty valuation - this
app has no ROS projection engine. Sleeper's own weekly projection covers
only the current week, and src/services/custom_projection.py's "second
model" is a 2025-season-average proxy, not a forward-looking model.
Averaging the two gives a number that's more stable than either alone (a
single week's matchup swing doesn't dominate, and a bye/no-projection
week doesn't zero out a real starter's value the way relying on the
weekly number alone would) - but it is still a rough proxy for "how good
is this player right now," not a claim of true dynasty/keeper value, and
every response using it says so explicitly rather than implying more
precision than the underlying data supports.
"""

from __future__ import annotations

from itertools import combinations

TRADE_VALUE_POSITIONS = ("QB", "RB", "WR", "TE")
# Real trades are almost never bigger than 2-for-2 in practice, and the
# combinatorial cost of considering every subset grows fast (a package
# of size k from a pool of n is C(n, k)) - capping at 2 per side keeps
# the search space small (a typical ~6-player offerable pool yields at
# most 21 pairs) while still covering the common real cases 1-for-1
# missed: consolidating two depth pieces into one difference-maker, or
# selling a locked-in bench stud for two useful role players.
MAX_PACKAGE_SIZE = 2


def trade_value(player: dict) -> float:
    weekly = player.get("projected_points") or 0.0
    season = player.get("custom_projected_points")
    if season is not None and weekly > 0:
        return round((weekly + season) / 2, 2)
    if season is not None:
        return round(season, 2)
    return round(weekly, 2)


def evaluate_trade(side_a: list[dict], side_b: list[dict]) -> dict:
    """Pure comparison of two arbitrary player lists - no ownership
    assumption, so this works for "my roster vs. an opponent's" or any
    two rosters in the league, matching how a real trade-analyzer tool
    is used (evaluate a proposal, not just "should I accept this").
    """
    def side_summary(players: list[dict]) -> dict:
        return {
            "players": [{"player_id": p["player_id"], "name": p["name"], "position": p.get("position"), "team": p.get("team"), "trade_value": trade_value(p)} for p in players],
            "total_value": round(sum(trade_value(p) for p in players), 2),
        }
    a, b = side_summary(side_a), side_summary(side_b)
    diff = round(a["total_value"] - b["total_value"], 2)
    larger = max(a["total_value"], b["total_value"])
    # Within 5% of the larger side's total counts as "fair" - trade value
    # here is already an approximation (see module docstring), so treating
    # every fractional-point difference as a decisive verdict would be
    # false precision.
    if larger == 0:
        verdict = "fair"
    elif abs(diff) <= 0.05 * larger:
        verdict = "fair"
    elif diff > 0:
        verdict = "side_a_favored"
    else:
        verdict = "side_b_favored"
    fairness_pct = round(100 * (1 - abs(diff) / larger), 1) if larger > 0 else 100.0
    return {
        "side_a": a,
        "side_b": b,
        "value_difference": diff,
        "fairness_pct": fairness_pct,
        "verdict": verdict,
        "note": "trade_value averages this week's Sleeper projection with the independent 2025-season-average model - a directional proxy for current value, not a rest-of-season or dynasty valuation.",
    }


def _position_profile(players: list[dict]) -> dict[str, list[float]]:
    """Sorted-descending trade values per position for one roster."""
    profile: dict[str, list[float]] = {pos: [] for pos in TRADE_VALUE_POSITIONS}
    for player in players:
        position = player.get("position")
        if position in profile:
            profile[position].append(trade_value(player))
    for position in profile:
        profile[position].sort(reverse=True)
    return profile


def _position_needs(my_profile: dict[str, list[float]], league_profiles: list[dict[str, list[float]]]) -> dict[str, dict]:
    """Compare my BEST player's value at each position against the
    league-wide average of every team's best player there - identifies
    where I'm below-average (need). Using each team's own best (not the
    whole league's average player) avoids a shallow league inflating
    "average" with backup-tier depth that was never a real comparison
    point. NOT used for surplus - see _surplus_positions for why "my
    best player is above average" is the wrong signal for that.
    """
    needs: dict[str, dict] = {}
    for position in TRADE_VALUE_POSITIONS:
        my_best = my_profile[position][0] if my_profile[position] else 0.0
        league_bests = [profile[position][0] for profile in league_profiles if profile[position]]
        league_avg_best = sum(league_bests) / len(league_bests) if league_bests else 0.0
        needs[position] = {"my_best": my_best, "league_avg_best": round(league_avg_best, 2), "delta": round(my_best - league_avg_best, 2)}
    return needs


def _direct_slot_counts(roster_positions: list[str]) -> dict[str, int]:
    counts = {position: 0 for position in TRADE_VALUE_POSITIONS}
    for slot in roster_positions:
        if slot in counts:
            counts[slot] += 1
    return counts


def _surplus_positions(my_players: list[dict], roster_positions: list[str]) -> set[str]:
    """A position counts as tradeable surplus if I'm rostering more
    real (nonzero-value) players there than this league's own
    direct-slot requirement plus one reserve.

    Confirmed live 2026-09-10: comparing "my best player's value vs.
    league average" (the signal _position_needs uses for need) is the
    WRONG signal for surplus - it flags a position as tradeable only
    when my headliner there happens to be elite, and misses the far more
    common real case of a position that's simply deep (many rostered,
    startable-tier players, no single standout). A real league roster
    with eight bench WRs and no single elite one produced ZERO trade
    suggestions under the old signal, even though that WR depth was
    obviously real, tradeable surplus.
    """
    direct = _direct_slot_counts(roster_positions)
    counts: dict[str, int] = {position: 0 for position in TRADE_VALUE_POSITIONS}
    for player in my_players:
        position = player.get("position")
        if position in counts and trade_value(player) > 0:
            counts[position] += 1
    return {position for position in TRADE_VALUE_POSITIONS if counts[position] > direct[position] + 1}


def _packages(pool: list[dict], max_size: int = MAX_PACKAGE_SIZE):
    """Every 1-player and (up to) max_size-player combination of pool,
    as a flat list of player dicts per combination."""
    for size in range(1, max_size + 1):
        for combo in combinations(pool, size):
            yield list(combo)


def _package_summary(players: list[dict]) -> list[dict]:
    return [{"player_id": p["player_id"], "name": p["name"], "position": p.get("position"), "trade_value": trade_value(p)} for p in players]


def suggest_trades(my_players: list[dict], my_starter_ids: set[str], other_rosters: list[dict], roster_positions: list[str], max_suggestions: int = 5) -> list[dict]:
    """Suggest trades - 1-for-1 up to MAX_PACKAGE_SIZE-for-MAX_PACKAGE_SIZE
    - between my roster and each other roster in the league.

    my_starter_ids: player_ids in MY currently-computed starting lineup.
    other_rosters: [{"roster_id", "team_name", "players": [scored player
    dicts, same shape as my_players], "starter_ids": {player_id, ...}},
    ...] - each roster's own currently-computed starting lineup, same
    roster_positions rules applied per team.

    Deliberately conservative, deterministic heuristics rather than an
    optimizer: nobody in a currently-computed starting lineup - mine or
    the other side's - is ever offerable, only bench depth. Confirmed
    live 2026-09-10 this was a real bug, not a hypothetical one: an
    earlier version only excluded my single best player AT A POSITION,
    which still let it offer away a real active FLEX/WR2 starter as
    "surplus depth" the moment a league started more than one player at
    that position - suggesting a manager casually trade away someone
    they just chose to start makes no sense regardless of how the value
    math works out. Suggestions are filtered to reasonably fair value
    (within 30% of each other by combined trade_value) so the list stays
    to packages a real league-mate might actually accept, not lopsided
    asks - and are ranked fairness-first, simplicity second, so a plain
    1-for-1 is preferred over an equally-fair but more complicated
    package.
    """
    surplus_positions = _surplus_positions(my_players, roster_positions)
    my_profile = _position_profile(my_players)
    other_profiles = [_position_profile(roster["players"]) for roster in other_rosters]
    needs = _position_needs(my_profile, [my_profile, *other_profiles])
    need_positions = {p for p, info in needs.items() if info["delta"] < 0}
    if not surplus_positions or not need_positions:
        return []

    # My tradeable depth pool: every surplus-position player NOT
    # currently in my starting lineup, pooled across positions so a
    # package can mix depth from more than one surplus spot. Zero-value
    # players (no projection and no season-average match - typically an
    # inactive or undrafted-rookie roster clog) are excluded here: they
    # add no real signal to a package, only a confusing "throw-in" that
    # doesn't move the value math but reads as clutter.
    my_offerable = [p for p in my_players if p.get("position") in surplus_positions and trade_value(p) > 0 and p["player_id"] not in my_starter_ids]
    if not my_offerable:
        return []
    give_packages = list(_packages(my_offerable))

    suggestions: list[dict] = []
    for roster in other_rosters:
        their_starter_ids = roster.get("starter_ids", set())
        their_offerable = [p for p in roster["players"] if p.get("position") in need_positions and trade_value(p) > 0 and p["player_id"] not in their_starter_ids]
        if not their_offerable:
            continue
        get_packages = list(_packages(their_offerable))

        for give in give_packages:
            give_value = sum(trade_value(p) for p in give)
            if give_value <= 0:
                continue
            for get in get_packages:
                get_value = sum(trade_value(p) for p in get)
                if get_value <= 0:
                    continue
                fairness = 1 - abs(give_value - get_value) / max(give_value, get_value)
                if fairness < 0.7:
                    continue
                give_positions = sorted({p.get("position") for p in give if p.get("position")})
                get_positions = sorted({p.get("position") for p in get if p.get("position")})
                suggestions.append({
                    "team_name": roster.get("team_name") or f"Roster {roster.get('roster_id')}",
                    "roster_id": roster.get("roster_id"),
                    "you_give": _package_summary(give),
                    "you_get": _package_summary(get),
                    "give_total": round(give_value, 2),
                    "get_total": round(get_value, 2),
                    "fairness_pct": round(fairness * 100, 1),
                    "rationale": f"Uses your {'/'.join(give_positions)} depth to address your {'/'.join(get_positions)} need.",
                })
    # Fairness first, then fewest total players moved - an equally fair
    # 1-for-1 is a simpler ask than a 2-for-2 and should surface first.
    suggestions.sort(key=lambda item: (-item["fairness_pct"], len(item["you_give"]) + len(item["you_get"])))
    # De-duplicate: the same exact give/get player set can otherwise
    # appear once per position pairing considered.
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for suggestion in suggestions:
        key = (suggestion["roster_id"], tuple(sorted(p["player_id"] for p in suggestion["you_give"])), tuple(sorted(p["player_id"] for p in suggestion["you_get"])))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(suggestion)
    return deduped[:max_suggestions]
