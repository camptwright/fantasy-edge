"""Historical NBA/WNBA results via the NBA Stats API (stats.nba.com).

There's no maintained lightweight client in this project's dependency list,
and stats.nba.com is notoriously strict about headers - a bare httpx request
gets a 403. This module talks to it directly through the shared `base`
fetcher with the header set that has proven to work.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.data.providers.base import fetch_json

_STATS_HEADERS = {
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
    "Accept-Language": "en-US,en;q=0.9",
}

_LEAGUE_ID = {"nba": "00", "wnba": "10"}


async def load_games(sport: str, season: str) -> list[dict[str, Any]]:
    """`season` is NBA's format, e.g. "2025-26"."""
    league_id = _LEAGUE_ID[sport]
    data = await fetch_json(
        "https://stats.nba.com/stats/leaguegamefinder",
        params={
            "LeagueID": league_id,
            "Season": season,
            "SeasonType": "Regular Season",
            "PlayerOrTeamAbbreviation": "T",
        },
        headers=_STATS_HEADERS,
    )
    result_set = data["resultSets"][0]
    headers = result_set["headers"]
    rows = result_set["rowSet"]

    idx = {name: i for i, name in enumerate(headers)}
    # leaguegamefinder returns one row per TEAM per game, not one per game -
    # pair them up by GAME_ID so we can emit a single home/away row.
    by_game: dict[str, dict[str, Any]] = {}
    for row in rows:
        game_id = row[idx["GAME_ID"]]
        matchup = row[idx["MATCHUP"]]
        is_home = "vs." in matchup
        entry = by_game.setdefault(game_id, {"game_id": game_id})
        side = "home" if is_home else "away"
        entry[f"{side}_team"] = row[idx["TEAM_NAME"]]
        entry[f"{side}_score"] = row[idx["PTS"]]
        entry["game_date"] = row[idx["GAME_DATE"]]

    out: list[dict[str, Any]] = []
    for entry in by_game.values():
        if "home_team" not in entry or "away_team" not in entry:
            continue
        game_date: date | None = None
        raw_date = entry.get("game_date")
        if raw_date:
            game_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        out.append(
            {
                "sport": sport,
                "season": season,
                "game_date": game_date,
                "home_team_name": entry["home_team"],
                "away_team_name": entry["away_team"],
                "home_score": entry.get("home_score"),
                "away_score": entry.get("away_score"),
            }
        )
    return out
