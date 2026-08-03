"""Historical NCAAF results via the `cfbd` (College Football Data) package.

Requires `cfbd_api_key` (free tier, sign up at collegefootballdata.com).
Deferred import for the same reason as nfl_loader: optional-dependency,
offline-script-only.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from config.settings import get_settings


def load_games(seasons: list[int]) -> list[dict[str, Any]]:
    import cfbd  # deferred: optional dependency

    settings = get_settings()
    if not settings.cfbd_api_key:
        raise RuntimeError("CFBD_API_KEY is not configured")

    configuration = cfbd.Configuration(access_token=settings.cfbd_api_key)
    rows: list[dict[str, Any]] = []

    with cfbd.ApiClient(configuration) as client:
        games_api = cfbd.GamesApi(client)
        for season in seasons:
            games = games_api.get_games(year=season)
            for g in games:
                if g.home_points is None or g.away_points is None:
                    continue
                game_date = None
                if g.start_date:
                    game_date = g.start_date.date() if hasattr(g.start_date, "date") else None
                rows.append(
                    {
                        "sport": "ncaaf",
                        "season": season,
                        "week": g.week,
                        "game_date": game_date,
                        "home_team_name": g.home_team,
                        "away_team_name": g.away_team,
                        "home_score": g.home_points,
                        "away_score": g.away_points,
                    }
                )
    return rows
