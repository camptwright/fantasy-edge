"""Historical NCAAF results via the CFBD (College Football Data) REST API,
called directly with httpx rather than the `cfbd` SDK package.

The `cfbd` package pins `pydantic<2` on every published release through at
least 5.21.0 (checked directly against the wheel metadata, not assumed) - a
permanent, unfixable conflict with this project's `pydantic>=2.9`
(FastAPI, pydantic-settings both need v2). No version pin resolves this;
`pip install .[historical]` fails `ResolutionImpossible` the moment `cfbd`
is in the same dependency set as the rest of the app. Calling the REST API
directly - the same pattern every other provider in this codebase already
uses (theodds_api.py, espn_api.py, underdog_api.py) - sidesteps the SDK
entirely and needs no extra dependency at all.

Requires `cfbd_api_key` (free tier, sign up at collegefootballdata.com).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from config.settings import get_settings
from src.data.providers.base import fetch_json

BASE_URL = "https://api.collegefootballdata.com"


async def load_games(seasons: list[int]) -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.cfbd_api_key:
        raise RuntimeError("CFBD_API_KEY is not configured")

    headers = {"Authorization": f"Bearer {settings.cfbd_api_key}"}
    rows: list[dict[str, Any]] = []

    for season in seasons:
        games = await fetch_json(
            f"{BASE_URL}/games",
            params={"year": season, "seasonType": "regular"},
            headers=headers,
        )
        for g in games:
            home_points = g.get("homePoints")
            away_points = g.get("awayPoints")
            if home_points is None or away_points is None:
                continue

            game_date: date | None = None
            start_date = g.get("startDate")
            if start_date:
                try:
                    game_date = datetime.fromisoformat(
                        start_date.replace("Z", "+00:00")
                    ).date()
                except ValueError:
                    game_date = None

            rows.append(
                {
                    "sport": "ncaaf",
                    "season": season,
                    "week": g.get("week"),
                    "game_date": game_date,
                    "home_team_name": g.get("homeTeam"),
                    "away_team_name": g.get("awayTeam"),
                    "home_score": home_points,
                    "away_score": away_points,
                }
            )
    return rows
