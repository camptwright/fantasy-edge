"""Public ESPN professional-sport injury reports, archived as evidence.

These rows are not a lineup feed and are never converted into a numeric
forecast adjustment.  Consumers must join athlete ids through a verified
source-specific identity rather than player name.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

import httpx

from config.settings import get_settings

_PATHS = {"nfl": "football/nfl", "nba": "basketball/nba", "mlb": "baseball/mlb", "nhl": "hockey/nhl"}


def athlete_id(athlete: dict) -> str | None:
    """ESPN injury payloads omit athlete.id but retain it in athlete links."""
    for link in athlete.get("links") or []:
        match = re.search(r"/id/(\d+)(?:/|$)", str((link or {}).get("href") or ""))
        if match:
            return match.group(1)
    return None


async def fetch_injury_reports() -> list[dict]:
    """Fetch bounded, flattened ESPN reports with one common observation time."""
    observed_at = datetime.now(timezone.utc).isoformat()
    settings = get_settings()
    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=20) as client:
        for sport, path in _PATHS.items():
            response = await client.get(f"{settings.espn_base_urls[sport] if sport in settings.espn_base_urls else 'https://site.api.espn.com/apis/site/v2/sports/' + path}/injuries")
            # ESPN does not currently configure MLB/NHL under espn_base_urls.
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("injuries"), list):
                raise ValueError(f"Invalid ESPN injury response for {sport}")
            for team in payload.get("injuries", []):
                if not isinstance(team, dict):
                    continue
                for injury in team.get("injuries", []):
                    athlete = injury.get("athlete") or {}
                    external_id = athlete_id(athlete)
                    if external_id is None:
                        continue
                    rows.append({"sport": sport, "team": team.get("displayName"), "athlete_id": external_id,
                                 "player_name": athlete.get("displayName"), "status": injury.get("status"),
                                 "reported_at": injury.get("date"), "short_comment": injury.get("shortComment"),
                                 "observed_at": observed_at, "provider": "espn_public_injuries"})
    return rows
