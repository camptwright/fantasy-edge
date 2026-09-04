"""Optional SportsDataIO weekly-NFL projection adapter.

The provider key is optional.  When it is absent this module makes no network
call, keeping Sleeper sync functional and avoiding an accidental scraped-data
fallback.  SportsDataIO records are normalized to Sleeper stat keys so every
league's native scoring settings continue to be the scoring authority.
"""

from __future__ import annotations

from typing import Any

import httpx

from config.settings import get_settings
from src.utils.normalize import normalize_player_name


# SportsDataIO field -> Sleeper scoring key. Fields not present in a response
# are simply omitted; formats with unsupported categories remain transparent.
STAT_FIELDS = {
    "PassingYards": "pass_yd",
    "PassingTouchdowns": "pass_td",
    "PassingInterceptions": "pass_int",
    "RushingYards": "rush_yd",
    "RushingTouchdowns": "rush_td",
    "Receptions": "rec",
    "ReceivingYards": "rec_yd",
    "ReceivingTouchdowns": "rec_td",
    "FumblesLost": "fum_lost",
    "FieldGoalsMade": "fgm",
    "ExtraPointsMade": "xpm",
}


def _name(row: dict[str, Any]) -> str:
    return str(row.get("Name") or " ".join(filter(None, [row.get("FirstName"), row.get("LastName")]))).strip()


def _catalog_index(catalog: dict[str, dict[str, Any]]) -> dict[tuple[str, str], str]:
    index: dict[tuple[str, str], str] = {}
    for sleeper_id, player in catalog.items():
        name = normalize_player_name(str(player.get("full_name") or ""))
        team = str(player.get("team") or "").upper()
        if name:
            index[(name, team)] = str(sleeper_id)
            index.setdefault((name, ""), str(sleeper_id))
    return index


async def weekly_projections(season: str, week: int, catalog: dict[str, dict[str, Any]]) -> list[dict] | None:
    """Fetch and normalize a weekly provider feed, or return None if disabled."""
    settings = get_settings()
    if not settings.sportsdataio_api_key:
        return None
    url = f"{settings.sportsdataio_projection_base_url.rstrip('/')}/PlayerGameProjectionStatsByWeek/{season}/{week}"
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.get(url, params={"key": settings.sportsdataio_api_key})
        response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("SportsDataIO projections response was not a list")
    index = _catalog_index(catalog)
    rows: list[dict] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        name, team = _name(row), str(row.get("Team") or "").upper()
        sleeper_id = index.get((normalize_player_name(name), team)) or index.get((normalize_player_name(name), ""))
        if not sleeper_id:
            continue
        stats = {target: row[field] for field, target in STAT_FIELDS.items() if row.get(field) is not None}
        rows.append({
            "player_id": sleeper_id,
            "player": {"first_name": name.split(" ", 1)[0] if name else "", "last_name": name.split(" ", 1)[1] if " " in name else "", "position": row.get("Position"), "injury_status": row.get("InjuryStatus")},
            "team": row.get("Team"),
            "opponent": row.get("Opponent"),
            "stats": stats,
            "provider": "sportsdataio",
            "provider_fantasy_points": row.get("FantasyPoints"),
        })
    return rows
