"""Engine v2 projections for decisions: the nearest scheduled week, as one checkpoint.

The owner put v2 into production on 2026-10-15 even though it failed its
registered 2022 test (docs/2026-10-15-engine-v2-plan.md). Decisions use it
only as half of a 50/50 points blend with the league's Sleeper projection,
the combination measured best on frozen 2026 data (fantasy_decision_models.
blend_engine_v2). Its frozen forecasts (projection_engine_v2_prospective)
keep grading it.

The payload matches projection_engine_serving's shape (players -> week ->
{game_id, stats}) so engine_research's reader and scorer apply unchanged.
Conditional on playing, QB/RB/WR/TE only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert

from src.models.governance import DerivedCheckpoint
from src.services import projection_engine_v2_prospective as P
from src.services.engine_research import V2_NAME
from src.services.forecast_evidence import digest


def nearest_week(games) -> list:
    """Every not-yet-started game of the earliest scheduled (season, week)."""
    if not games:
        return []
    first = min((g.season, g.week) for g in games if g.week is not None)
    return [g for g in games if (g.season, g.week) == first]


def payload(projected: dict, now: datetime) -> dict:
    players, games = {}, {}
    for r in projected["rows"]:
        if r["player"] is None:
            continue
        g = r["db_game"]
        games[str(g.id)] = {"week": g.week, "kickoff": g.game_time.isoformat(), "environment": "market_line"}
        players.setdefault(str(r["player"]), {})[str(g.week)] = {"game_id": str(g.id), "position": r["position"],
                                                                 "stats": r["stats"]}
    return {"status": "research", "generated_at": now.isoformat(), "engine_version": projected["version"],
            "recipe": P.RECIPE, "decision_use": "blend_half_with_provider", "games": games, "players": players,
            "unmatched": projected["unmatched"], "conditional_on_playing": True}


async def store(db, body: dict) -> None:
    values = {"name": V2_NAME, "digest": digest(body), "payload": body, "updated_at": datetime.now(timezone.utc)}
    statement = insert(DerivedCheckpoint).values(**values)
    await db.execute(statement.on_conflict_do_update(
        index_elements=["name"], set_={k: getattr(statement.excluded, k) for k in values if k != "name"}))
    await db.commit()


async def run(db, *, now: datetime | None = None, loaded: tuple | None = None) -> dict:
    """One fit: serve the nearest week and freeze the capture window's forecasts."""
    now = now or datetime.now(timezone.utc)
    upcoming = await P.scheduled(db, now)
    serve, window = nearest_week(upcoming), P.target_games(upcoming, now)
    games = list({g.id: g for g in serve + window}.values())
    if not games:
        return {"serving": {"status": "no_remaining_games"}, "capture": {"status": "no_games_in_window", "captured": 0}}
    projected = await P.project(db, games, now=now, loaded=loaded)
    serving = {"status": projected["status"]}
    if projected["rows"]:
        served = {g.id for g in serve}
        body = payload({**projected, "rows": [r for r in projected["rows"] if r["db_game"].id in served]}, now)
        await store(db, body)
        serving = {"status": "refreshed", "players": len(body["players"]), "games": len(body["games"]),
                   "version": projected["version"]}
    capture = await P.capture(db, now=now, projected=projected) if window else {
        "status": "no_games_in_window", "captured": 0}
    return {"serving": serving, "capture": capture}
