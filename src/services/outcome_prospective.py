"""Prospective check of the simulated matchup win probability.

The fitted outcome model was validated on only 24 past matchups. This grows
that sample honestly: every run freezes the current pregame win probability
from each league's saved checkpoint (only while no starter's game has begun -
the simulation itself withholds otherwise), and once the NFL week is final the
latest pregame capture per matchup is graded against the platform result.

Research evidence only; nothing is promoted or changed by these reports.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import or_, select

from config.settings import get_settings
from src.models.facts import Game
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot
from src.services.roster_stat_prospective import publish

SETTLE = timedelta(hours=24)  # results settle (stat corrections) a day after the last kickoff


def archive_root() -> Path:
    return Path(get_settings().raw_archive_dir) / "outcome-prospective"


def season_of(now: datetime) -> int:
    return now.year if now.month >= 3 else now.year - 1


def forecast(data: dict, now: datetime) -> dict | None:
    """A capture row from a checkpoint, or None when it is not a valid pregame forecast."""
    sim = data.get("outcome_simulation") or {}
    rosters = data.get("matchup_rosters") or {}
    mine, theirs = rosters.get("mine") or {}, rosters.get("opponent") or {}
    current = sim.get("current") or {}
    p = current.get("win_probability")
    starters = [str(x) for side in (mine, theirs) for x in side.get("starters", [])]
    ranges = sim.get("player_ranges") or {}
    # A starter on bye or ruled out is a known zero, not a game in progress:
    # only a recorded final result means kickoff has passed for that starter.
    started = any((ranges.get(pid) or {}).get("basis") == "final_recorded" for pid in starters)
    if (sim.get("status") != "estimated_research" or started
            or not isinstance(p, (int, float)) or not math.isfinite(p)
            or mine.get("roster_id") is None or theirs.get("roster_id") is None or data.get("week") is None):
        return None
    return {"league_id": data.get("league_id"), "season": season_of(now), "week": int(data["week"]),
            "roster_id": mine["roster_id"], "opponent_roster_id": theirs["roster_id"], "captured_at": now.isoformat(),
            "win_probability": round(float(p), 4), "mean": current.get("mean"), "opponent_mean": current.get("opponent_mean"),
            "model_fitted_at": (sim.get("model") or {}).get("fitted_at")}


async def capture(db, now: datetime | None = None, root: Path | None = None) -> int:
    from src.services.workspace_checkpoints import read
    now, root = now or datetime.now(timezone.utc), root or archive_root()
    ids = (await db.scalars(select(SleeperLeague.league_id).where(SleeperLeague.sport == "nfl"))).all()
    captured = 0
    for league_id in ids:
        data = await read(db, league_id)
        row = forecast({**data, "league_id": league_id}, now) if data else None
        if row:
            publish(root / "forecasts" / f"{league_id}-{row['season']}-w{row['week']:02d}-r{row['roster_id']}-"
                    f"{now.strftime('%Y%m%dT%H%M%S%f')}.json", row)
            captured += 1
    return captured


def score(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "weeks": [], "brier": None, "coin_flip_brier": 0.25, "log_loss": None}
    eps = 1e-6
    briers = [(r["win_probability"] - r["won"]) ** 2 for r in rows]
    losses = [-math.log(max(eps, r["win_probability"] if r["won"] else 1 - r["win_probability"])) for r in rows]
    bins = {}
    for r in rows:
        b = min(4, int(r["win_probability"] * 5))
        bins.setdefault(b, []).append(r)
    return {"n": len(rows), "weeks": sorted({(r["season"], r["week"]) for r in rows}),
            "brier": round(sum(briers) / len(rows), 4), "coin_flip_brier": 0.25,
            "log_loss": round(sum(losses) / len(rows), 4),
            "calibration": [{"bin": f"{b * 20}-{b * 20 + 20}%", "n": len(v),
                             "mean_forecast": round(sum(r["win_probability"] for r in v) / len(v), 3),
                             "win_rate": round(sum(r["won"] for r in v) / len(v), 3)} for b, v in sorted(bins.items())]}


async def report(db, now: datetime | None = None, root: Path | None = None) -> dict:
    now, root = now or datetime.now(timezone.utc), root or archive_root()
    latest: dict[tuple, dict] = {}
    for path in sorted((root / "forecasts").glob("*.json")):
        r = json.loads(path.read_text())
        key = (r["league_id"], r["season"], r["week"], r["roster_id"])
        if key not in latest or r["captured_at"] > latest[key]["captured_at"]:
            latest[key] = r
    statuses: dict[str, int] = {}
    graded, final_weeks = [], {}
    for (league_id, season, week, roster_id), r in sorted(latest.items(), key=lambda kv: kv[0]):
        if (season, week) not in final_weeks:
            games = (await db.scalars(select(Game).where(Game.sport == "nfl", Game.season == season, Game.week == week,
                                                         or_(Game.game_type.is_(None), Game.game_type == "REG")))).all()
            last = max((g.game_time for g in games if g.game_time), default=None)
            final_weeks[(season, week)] = last if games and last and all(
                g.status == "final" and g.game_time for g in games) and now - last >= SETTLE else None
        last = final_weeks[(season, week)]
        if last is None:
            statuses["awaiting_final_week"] = statuses.get("awaiting_final_week", 0) + 1
            continue
        snapshot = await db.get(SleeperLeagueSnapshot, (league_id, week, "matchups"))
        rows = {row.get("roster_id"): row for row in (snapshot.payload if snapshot and isinstance(snapshot.payload, list) else [])}
        a, b = rows.get(r["roster_id"]), rows.get(r["opponent_roster_id"])
        if snapshot is None or snapshot.synced_at < last + timedelta(hours=6) or not a or not b:
            statuses["result_snapshot_missing_or_early"] = statuses.get("result_snapshot_missing_or_early", 0) + 1
            continue
        pa, pb = a.get("points"), b.get("points")
        if not all(isinstance(x, (int, float)) for x in (pa, pb)) or pa == pb:
            statuses["no_decisive_result"] = statuses.get("no_decisive_result", 0) + 1
            continue
        statuses["graded"] = statuses.get("graded", 0) + 1
        graded.append({**r, "won": int(pa > pb), "points": pa, "opponent_points": pb})
    out = {"generated_at": now.isoformat(), "status": "prospective_research", "serving_promoted": False,
           "captured_matchups": len(latest), "statuses": statuses, "summary": score(graded)}
    publish(root / "reports" / f"{now.strftime('%Y%m%dT%H%M%S%f')}.json", out)
    return out
