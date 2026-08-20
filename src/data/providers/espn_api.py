"""ESPN's unofficial public API. Free, no key, no rate limit we've ever hit.

This is the game-sync backbone for all 8 sports: it has no quota, so it is
safe to poll aggressively and is the source of truth for which games exist,
their status (scheduled/live/final), and final scores. The Odds API is only
ever asked about games ESPN already knows about.

`espn_path` per sport lives in config/sports.yaml because ESPN's URL scheme
is `sport/league` (e.g. "basketball/nba", "football/college-football") and
does not follow one consistent pattern - college sports insert "college-" in
different spots, hockey has one league, etc.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from config.settings import get_sport_config
from src.data.providers.base import fetch_json
from src.utils.logging import get_logger

log = get_logger(__name__)

# The site.api host currently returns an Akamai 403 from CT100's network,
# while the equivalent site.web.api host serves the same scoreboard payload.
# Keep this as a provider detail so game sync remains keyless and resilient.
BASE_URL = "https://site.web.api.espn.com/apis/site/v2/sports"
CORE_BASE_URL = "https://sports.core.api.espn.com/v2/sports"

# ESPN's status.type.state values, mapped to our games.status check constraint.
_STATE_TO_STATUS = {
    "pre": "scheduled",
    "in": "live",
    "post": "final",
}


def _map_status(event: dict[str, Any]) -> str:
    state = (
        event.get("status", {}).get("type", {}).get("state")
        or event.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("state")
    )
    if state == "post":
        detail = event.get("status", {}).get("type", {}).get("name", "")
        if detail in ("STATUS_POSTPONED",):
            return "postponed"
        if detail in ("STATUS_CANCELED", "STATUS_CANCELLED"):
            return "cancelled"
    return _STATE_TO_STATUS.get(state, "scheduled")


async def get_scoreboard(sport: str, *, day: date | None = None) -> list[dict[str, Any]]:
    """Raw ESPN scoreboard events for one sport, optionally pinned to a date.

    Without `day`, ESPN returns "today plus the current window" which for
    most sports is a few days of games - enough for game_sync_agent to run
    on a short interval and stay current without ever paging.
    """
    cfg = get_sport_config(sport)
    espn_path = cfg["espn_path"]
    params: dict[str, Any] = {"limit": 200}
    if day is not None:
        params["dates"] = day.strftime("%Y%m%d")

    data = await fetch_json(f"{BASE_URL}/{espn_path}/scoreboard", params=params)
    return data.get("events", [])


def parse_event(sport: str, event: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten one ESPN scoreboard event into the shape game_sync_agent upserts.

    Returns None for events missing the competitor data we need - ESPN
    occasionally publishes placeholder TBD entries for future rounds.
    """
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    competition = competitions[0]
    competitors = competition.get("competitors") or []
    if len(competitors) != 2:
        return None

    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if home is None or away is None:
        return None

    def _score(c: dict[str, Any]) -> int | None:
        raw = c.get("score")
        try:
            return int(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            return None

    return {
        "sport": sport,
        "espn_event_id": str(event.get("id")),
        "game_time": event.get("date"),  # ISO8601, may be absent pre-schedule
        "status": _map_status(event),
        "home_team_name": (home.get("team") or {}).get("displayName"),
        "away_team_name": (away.get("team") or {}).get("displayName"),
        "home_team_espn_id": (home.get("team") or {}).get("id"),
        "away_team_espn_id": (away.get("team") or {}).get("id"),
        "home_score": _score(home),
        "away_score": _score(away),
        "season": ((event.get("season") or {}).get("year")),
        "week": ((event.get("week") or {}).get("number")),
    }


async def get_games(sport: str, *, day: date | None = None) -> list[dict[str, Any]]:
    """Parsed, upsert-ready game dicts for one sport."""
    events = await get_scoreboard(sport, day=day)
    games = [parse_event(sport, e) for e in events]
    return [g for g in games if g is not None]


async def get_injuries(sport: str) -> list[dict[str, Any]]:
    """Team injury reports. Best-effort: not every ESPN league exposes this,
    so an empty list is a normal outcome, not an error."""
    cfg = get_sport_config(sport)
    espn_path = cfg["espn_path"]
    try:
        data = await fetch_json(f"{BASE_URL}/{espn_path}/injuries")
    except Exception:
        log.info("espn.injuries_unavailable", sport=sport)
        return []
    return data.get("injuries", [])


def parse_game_odds(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract ESPN's published game markets without guessing missing values.

    ESPN exposes these on the scoreboard competition (spread, moneyline and
    total).  The shape has changed between API versions, so every field is
    optional and the raw provider name is retained for provenance.
    """
    competition = (event.get("competitions") or [{}])[0]
    odds = competition.get("odds") or []
    if not odds:
        return []
    book = odds[0] or {}
    event_id = str(event.get("id"))
    rows: list[dict[str, Any]] = []

    def add(market: str, selection: str, line: Any, price: Any = None) -> None:
        if line is None and price is None:
            return
        try:
            numeric_line = float(line) if line is not None else None
        except (TypeError, ValueError):
            numeric_line = None
        try:
            numeric_price = int(price) if price is not None else None
        except (TypeError, ValueError):
            numeric_price = None
        rows.append({"event_id": event_id, "market": market, "selection": selection,
                     "line": numeric_line, "price_american": numeric_price,
                     "source": "espn", "observed_at": event.get("date")})

    add("total", "game", book.get("overUnder"))
    add("spread", "home", book.get("spread"))
    add("moneyline", "home", (book.get("homeTeamOdds") or {}).get("moneyLine"))
    add("moneyline", "away", (book.get("awayTeamOdds") or {}).get("moneyLine"))
    return rows


async def get_nfl_game_odds() -> list[dict[str, Any]]:
    """Return current ESPN NFL game markets for the prediction board."""
    events = await get_scoreboard("nfl")
    rows: list[dict[str, Any]] = []
    for event in events:
        rows.extend(parse_game_odds(event))
    return rows
