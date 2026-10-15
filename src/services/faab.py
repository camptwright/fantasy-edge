"""FAAB bid ranges for waiver adds, shown only in leagues that bid (Sleeper waiver_type 2).

No league here uses FAAB today; this is inert until one does. It is a pacing
rule, not a model of rival bids:

- value: the add's lineup gain over the selected horizon h, from
  waiver_guidance (engine research, not validated);
- pace: if a comparable best add appeared every h weeks for the W regular-season
  weeks left, the season's waiver value would be about best_gain * W / h, so
  this add is worth budget * gain / (best_gain * W / h) of what you have left;
- range: half to one-and-a-half times that, never above your budget, and
  never above the largest rival budget + 1 (a higher bid buys nothing more
  when ties go by waiver order);
- league history: when this league's completed FAAB claims are synced, the
  median winning share of the budget is reported beside the range for context.

All figures are whole dollars of the league's own budget and assume nothing
about how rivals value the player.
"""

from __future__ import annotations

from math import isfinite
from statistics import median

REGULAR_SEASON_LAST_WEEK = 14  # Sleeper default playoff start is week 15


def _num(v):
    return type(v) in (int, float) and isfinite(v)


def budgets(settings: dict, rosters: list[dict]) -> dict | None:
    """{budget, min_bid, remaining: {roster_id: dollars}} or None when the league does not bid."""
    if (settings or {}).get("waiver_type") != 2:
        return None
    budget = settings.get("waiver_budget")
    if not _num(budget) or budget <= 0:
        return None
    remaining = {}
    for r in rosters:
        used = (r.get("settings") or {}).get("waiver_budget_used") or 0
        remaining[r["roster_id"]] = max(0, int(budget) - int(used)) if _num(used) else None
    return {"budget": int(budget), "min_bid": 1 if settings.get("waiver_bid_min") == 1 else 0, "remaining": remaining}


def history_share(transactions: list, budget: int) -> dict:
    """Median winning bid as a share of the starting budget, from completed FAAB claims."""
    bids = [t["settings"]["waiver_bid"] for t in transactions or []
            if isinstance(t, dict) and t.get("type") == "waiver" and t.get("status") == "complete"
            and _num((t.get("settings") or {}).get("waiver_bid"))]
    return {"claims": len(bids), "median_share": round(median(bids) / budget, 3) if bids and budget else None}


def bids(rows: list[dict], money: dict | None, my_roster_id, week: int | None, *,
         playoff_start: int | None = None, history: dict | None = None) -> dict:
    if money is None:
        return {"status": "not_a_faab_league", "rows": []}
    mine = money["remaining"].get(my_roster_id)
    if mine is None:
        return {"status": "budget_unknown", "rows": []}
    last = (playoff_start - 1) if _num(playoff_start) and playoff_start > 1 else REGULAR_SEASON_LAST_WEEK
    weeks_left = max(1, last - week + 1) if _num(week) else None
    rivals = [v for k, v in money["remaining"].items() if k != my_roster_id and v is not None]
    ceiling = min(mine, (max(rivals) + 1) if rivals else mine)
    gains = [r for r in rows if _num(r.get("lineup_gain")) and r["lineup_gain"] > 0 and not r.get("stream")]
    if not gains or weeks_left is None or mine <= 0:
        return {"status": "no_bids", "rows": [], "remaining_budget": mine, "weeks_left": weeks_left}
    best = max(r["lineup_gain"] for r in gains)
    out = []
    for r in gains:
        horizon = r.get("weeks") or 2
        share = min(1.0, r["lineup_gain"] / (best * max(1.0, weeks_left / horizon)))
        fair = mine * share
        low, high = (max(money["min_bid"], min(ceiling, round(fair * f))) for f in (0.5, 1.5))
        out.append({"add_id": r["add_id"], "drop_id": r["drop_id"], "lineup_gain": r["lineup_gain"],
                    "share_of_remaining": round(share, 3), "bid_low": low, "bid_high": max(low, high)})
    return {"status": "pacing_estimate", "rows": out, "remaining_budget": mine, "budget": money["budget"],
            "weeks_left": weeks_left, "rival_max_remaining": max(rivals) if rivals else None,
            "league_history": history or {"claims": 0, "median_share": None},
            "note": "Pacing estimate from engine-research lineup gains and your remaining budget; "
                    "not a prediction of rival bids. Capped at the largest rival budget + 1."}
