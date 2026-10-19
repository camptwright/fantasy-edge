"""Sleeper's season-long projections (RotoWire), frozen as they change, for a future engine v2 prior.

The owner approved this prior for v2 (2026-10-15), but Sleeper's own history
is revised after games (docs/2026-10-15-engine-v2-plan.md, archive leakage),
so a prior can only be tested from copies frozen at the time. This captures
them going forward; nothing reads them yet.

GET api.sleeper.com/projections/nfl/{season}?season_type=regular&position[]=QB..TE
(undocumented; verified live 2026-10-18: 3117 rows, company "rotowire",
game_id "season", `last_modified` in ms, `week_shard` the update week).
A file is written only when the newest `last_modified` moves, create-only,
under raw/sleeper-season-projections. ADP fields are dropped.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx

from config.settings import get_settings
from src.services.roster_stat_prospective import publish

URL = "https://api.sleeper.com/projections/nfl/{season}"
POSITIONS = ("QB", "RB", "WR", "TE")
DIRECTORY = "sleeper-season-projections"


async def fetch(season: int) -> list[dict]:
    params = [("season_type", "regular"), *(("position[]", p) for p in POSITIONS)]
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(URL.format(season=season), params=params)
        r.raise_for_status()
    rows = r.json()
    if not isinstance(rows, list):
        raise ValueError("season projections are not a list")
    return rows


def trim(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("player_id") or not isinstance(row.get("stats"), dict):
            continue
        out.append({"player_id": str(row["player_id"]), "team": row.get("team"),
                    "position": (row.get("player") or {}).get("position"), "company": row.get("company"),
                    "week_shard": row.get("week_shard"), "last_modified": row.get("last_modified"),
                    "stats": {k: v for k, v in row["stats"].items() if not k.startswith("adp_")}})
    return out


async def capture(db=None, *, season: int | None = None, now: datetime | None = None, fetcher=fetch) -> dict:
    now = now or datetime.now(timezone.utc)
    season = season or (now.year if now.month >= 3 else now.year - 1)
    try:
        rows = trim(await fetcher(season))
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {"status": "sleeper_unavailable", "error": type(exc).__name__}
    stamps = [r["last_modified"] for r in rows if isinstance(r["last_modified"], int)]
    if not stamps:
        return {"status": "no_projections", "rows": len(rows)}
    modified = max(stamps)
    path = Path(get_settings().raw_archive_dir) / DIRECTORY / f"{season}_{modified}.json"
    written = publish(path, {"season": season, "captured_at": now.isoformat(), "last_modified": modified,
                             "source": "sleeper_season_projections", "rows": rows})
    return {"status": "captured" if written else "unchanged", "rows": len(rows), "last_modified": modified}
