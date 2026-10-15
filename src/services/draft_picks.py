"""Rookie-pick ownership and observed market prices for dynasty trades.

Ownership: every roster owns its own picks for the next SEASONS_AHEAD drafts
and `league.settings.draft_rounds` rounds, then Sleeper's public
/league/{id}/traded_picks (synced as the 'traded_picks' snapshot) moves each
traded pick to its current owner. Without that snapshot ownership is
unverified and no inventory is offered.

Price: the same daily FantasyCalc archive as player values
(src/services/fantasy_market.py), whose dynasty payload carries picks as
`FP_{season}_{round}` and, for the next draft, `FP_{season}_{tier}_{round-1}`
with tier early/mid/late. A next-draft pick takes the tier of its original
roster's place in the current standings (wins, then points; worst third
early) once MIN_GAMES are played; the real draft order is the league's rule,
so the basis says "estimated". Market-index units, not fantasy points.
"""

from __future__ import annotations

SEASONS_AHEAD = 3
MIN_GAMES = 4
TIERS = ("early", "mid", "late")


def ownership(season: int, rounds: int, roster_ids: list[int], traded: list[dict]) -> list[dict]:
    owner = {(s, r, o): o for s in range(season + 1, season + 1 + SEASONS_AHEAD)
             for r in range(1, rounds + 1) for o in roster_ids}
    for t in traded:
        try:
            key = (int(t["season"]), int(t["round"]), int(t["roster_id"]))
        except (KeyError, TypeError, ValueError):
            continue
        if key in owner and t.get("owner_id") is not None:
            owner[key] = int(t["owner_id"])
    return [{"id": f"{s}-{r}-{o}", "season": s, "round": r, "original_roster_id": o, "owner_roster_id": current}
            for (s, r, o), current in sorted(owner.items())]


def tiers(rosters: list) -> dict[int, str]:
    """original roster id -> early/mid/late from current standings; {} before MIN_GAMES."""
    def record(r):
        s = r.settings or {}
        wins, losses, ties = (int(s.get(k) or 0) for k in ("wins", "losses", "ties"))
        points = float(s.get("fpts") or 0) + float(s.get("fpts_decimal") or 0) / 100
        return wins, losses, ties, points
    rows = [(r.roster_id, *record(r)) for r in rosters]
    if not rows or min(w + l + t for _, w, l, t, _ in rows) < MIN_GAMES:
        return {}
    order = sorted(rows, key=lambda x: (x[1] + x[3] / 2, x[4]))  # worst first
    third = len(order) / 3
    return {rid: TIERS[min(2, int(i // third))] for i, (rid, *_) in enumerate(order)}


def price(pick: dict, values: dict[str, float], next_season: int, tier_of: dict[int, str]) -> dict:
    tier = tier_of.get(pick["original_roster_id"]) if pick["season"] == next_season else None
    if tier:
        key = f"FP_{pick['season']}_{tier}_{pick['round'] - 1}"
        if key in values:
            return {"value": values[key], "market_id": key, "basis": f"{tier}_round_estimated_from_current_standings"}
    key = f"FP_{pick['season']}_{pick['round']}"
    if key in values:
        return {"value": values[key], "market_id": key, "basis": "generic_round"}
    return {"value": None, "market_id": None, "basis": "not_priced_by_market"}


def inventory(league, rosters: list, traded: list[dict] | None, market: dict | None) -> dict:
    if traded is None:
        return {"status": "ownership_not_synced", "picks": []}
    rounds = int((league.settings or {}).get("draft_rounds") or 0)
    if rounds < 1 or not rosters:
        return {"status": "no_rookie_draft", "picks": []}
    season = int(league.season)
    picks = ownership(season, rounds, [r.roster_id for r in rosters], traded)
    values = {r["sleeper_id"]: r["value"] for r in (market or {}).get("rows", [])
              if r.get("position") == "PICK" and r.get("sleeper_id")}
    tier_of = tiers(rosters)
    for p in picks:
        p.update(price(p, values, season + 1, tier_of))
    return {"status": "observed" if values else "ownership_only", "picks": picks,
            "ownership_source": "sleeper_traded_picks",
            "market_captured_at": (market or {}).get("captured_at"),
            "attribution": "FantasyCalc" if values else None,
            "note": "Ownership from Sleeper; prices are FantasyCalc market-index values, not fantasy points. "
                    "Next-draft tiers are estimated from current standings, not the league's final draft order."}
