"""Sleeper's public trending adds: the crowd signal behind "most added" lists.

GET /players/nfl/trending/add?lookback_hours=24&limit=N returns
[{player_id, count}] (Sleeper asks for attribution). Shown beside waiver
guidance as context; it never ranks or changes a recommendation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.dialects.postgresql import insert

from config.settings import get_settings
from src.models.governance import DerivedCheckpoint
from src.services.forecast_evidence import digest

NAME = "sleeper_trending:add"
REFRESH = timedelta(hours=1)
LOOKBACK_HOURS = 24


async def fetch(limit: int = 100) -> dict[str, int]:
    async with httpx.AsyncClient(base_url=get_settings().sleeper_base_url, timeout=20) as client:
        r = await client.get("/players/nfl/trending/add", params={"lookback_hours": LOOKBACK_HOURS, "limit": limit})
        r.raise_for_status()
    return {str(row["player_id"]): int(row["count"]) for row in r.json()
            if isinstance(row, dict) and row.get("player_id") and isinstance(row.get("count"), int)}


async def refresh(db, *, now: datetime | None = None, fetcher=fetch) -> dict:
    now = now or datetime.now(timezone.utc)
    row = await db.get(DerivedCheckpoint, NAME)
    if row and now - datetime.fromisoformat(row.payload["fetched_at"]) < REFRESH:
        return {"status": "fresh"}
    try:
        players = await fetcher()
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return {"status": "sleeper_unavailable", "error": type(exc).__name__}
    payload = {"fetched_at": now.isoformat(), "lookback_hours": LOOKBACK_HOURS, "players": players,
               "attribution": "Sleeper"}
    values = {"name": NAME, "digest": digest(payload), "payload": payload, "updated_at": now}
    statement = insert(DerivedCheckpoint).values(**values)
    await db.execute(statement.on_conflict_do_update(
        index_elements=["name"], set_={k: getattr(statement.excluded, k) for k in values if k != "name"}))
    await db.commit()
    return {"status": "refreshed", "players": len(players)}


async def latest(db, *, now: datetime | None = None, max_age: timedelta = timedelta(hours=6)) -> dict | None:
    row = await db.get(DerivedCheckpoint, NAME)
    now = now or datetime.now(timezone.utc)
    if row is None or now - datetime.fromisoformat(row.payload["fetched_at"]) > max_age:
        return None
    return row.payload
