"""Historical NHL results via the NHL API v1 (api-web.nhle.com). Free, no key.

The v1 API has no single "give me the whole league's season" endpoint - the
closest primitive is a per-team season schedule
(`/v1/club-schedule-season/{team}/{season}`). This loader walks all 32 teams
and dedupes by `gameId` since every game appears twice (once per team).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.data.providers.base import fetch_json
from src.utils.logging import get_logger

log = get_logger(__name__)

# Current NHL team abbreviations (32 teams, 2024-25 alignment).
TEAM_ABBREVIATIONS = [
    "ANA", "ARI", "BOS", "BUF", "CAR", "CBJ", "CGY", "CHI", "COL", "DAL",
    "DET", "EDM", "FLA", "LAK", "MIN", "MTL", "NJD", "NSH", "NYI", "NYR",
    "OTT", "PHI", "PIT", "SEA", "SJS", "STL", "TBL", "TOR", "UTA", "VAN",
    "VGK", "WPG", "WSH",
]


async def load_games(season: str) -> list[dict[str, Any]]:
    """`season` is NHL's 8-digit format, e.g. "20252026"."""
    by_game_id: dict[int, dict[str, Any]] = {}

    for team in TEAM_ABBREVIATIONS:
        try:
            data = await fetch_json(
                f"https://api-web.nhle.com/v1/club-schedule-season/{team}/{season}"
            )
        except Exception:
            # Expansion/relocation teams (e.g. ARI -> UTA) 404 for seasons
            # they didn't exist in. Skip rather than abort the whole load.
            log.info("nhl_loader.team_unavailable", team=team, season=season)
            continue

        for game in data.get("games", []):
            if game.get("gameType") != 2:  # 2 = regular season
                continue
            if game.get("gameState") not in ("OFF", "FINAL"):
                continue
            game_id = game.get("id")
            if game_id in by_game_id:
                continue

            game_date_raw = game.get("gameDate")
            game_date: date | None = None
            if game_date_raw:
                game_date = datetime.strptime(game_date_raw, "%Y-%m-%d").date()

            home = game.get("homeTeam", {})
            away = game.get("awayTeam", {})
            by_game_id[game_id] = {
                "sport": "nhl",
                "season": season,
                "game_date": game_date,
                # The v1 schema has no "name" key at all (verified live
                # 2026-08-06 against a real club-schedule-season response) -
                # every homeTeam/awayTeam only has commonName (mascot only,
                # e.g. "Maple Leafs") + placeName (city only) + abbrev. Use
                # abbrev directly: config/team_aliases/nhl.yaml crosswalks
                # it to ESPN's canonical full name/espn_id, same pattern as
                # every other sport's abbreviation-keyed loader.
                "home_team_name": home.get("abbrev"),
                "away_team_name": away.get("abbrev"),
                "home_score": home.get("score"),
                "away_score": away.get("score"),
            }

    return list(by_game_id.values())
