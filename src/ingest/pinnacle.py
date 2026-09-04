"""Pinnacle sharp-line reference via guest.api.arcadia.pinnacle.com.

Pinnacle's own paid API suite closed to the public 2025-07-23 (its docs say
so directly); guest.api.arcadia is the same public site's own consumer API
and needs no account, just the X-API-Key in config/settings.py.

Two endpoints are combined: `/leagues/{id}/matchups` (which games exist -
team names, kickoff, and whether an entry is a genuine two-team game versus
a "special" prop-style matchup) and `/leagues/{id}/markets/straight` (the
actual moneyline/spread/total prices, one row per matchupId/type/line).
Matchups carry no price and markets carry no team names, so a game has to
be resolved from the first before its prices from the second mean anything.

SIGN: verified live 2026-09-03 (Rams -3.5 home favourite over the 49ers) -
Pinnacle's own `points` field on each spread/total price already matches
this app's storage convention (home's handicap negative when favoured), so
no negation is applied here, same as theodds.py's equivalent note.

Pinnacle publishes many alternate lines per matchup (multiple spread/total
entries at different points, all sharing one matchupId) - only the entry
with `isAlternate: false` is the book's actual current line; the rest are
skipped, matching the meaning of "the current spread/total" everywhere else
in this schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.data.scrapers.base import BaseScraper, ScraperError
from src.ingest.games import find_game_by_teams
from src.ingest.identity import resolve_team
from src.ingest.lines import record_team_line
from src.ingest.runs import record_run

SOURCE = "pinnacle"


class PinnacleScraper(BaseScraper):
    source = SOURCE
    min_interval = 3.0


def _auth_headers() -> dict[str, str]:
    return {
        "X-API-Key": get_settings().pinnacle_api_key,
        "Referer": "https://www.pinnacle.com/",
    }


async def poll_team_markets(db: AsyncSession, sport: str = "nfl") -> int:
    """Poll moneyline/spread/total for one sport. Returns rows written."""
    settings = get_settings()
    league_id = settings.pinnacle_league_ids.get(sport)
    if league_id is None:
        return 0

    scraper = PinnacleScraper()
    async with record_run(db, f"{SOURCE}_{sport}") as run:
        try:
            matchups = await scraper.fetch_json(
                f"{settings.pinnacle_base_url}/leagues/{league_id}/matchups",
                headers=_auth_headers(),
            )
            markets = await scraper.fetch_json(
                f"{settings.pinnacle_base_url}/leagues/{league_id}/markets/straight",
                headers=_auth_headers(),
            )
        except ScraperError as exc:
            run.detail = str(exc)
            raise RuntimeError(str(exc)) from None

        fixtures = _index_game_matchups(matchups)

        for market in markets:
            if (
                market.get("period") != 0
                or market.get("isAlternate") is not False
                or market.get("status") != "open"
            ):
                continue
            fixture = fixtures.get(market.get("matchupId"))
            if fixture is None:
                continue
            home_name, away_name, kickoff = fixture
            try:
                home = await resolve_team(db, home_name, sport=sport)
                away = await resolve_team(db, away_name, sport=sport)
            except LookupError:
                continue
            game = await find_game_by_teams(
                db, home_team_id=home.id, away_team_id=away.id, kickoff=kickoff
            )
            if game is None:
                continue
            for row in _rows_for(market):
                if await record_team_line(
                    db, game_id=game.id, source=SOURCE, line_type="live", **row
                ):
                    run.rows_written += 1
        await db.commit()
        return run.rows_written


def _index_game_matchups(
    matchups: list[dict[str, Any]],
) -> dict[int, tuple[str, str, datetime | None]]:
    """Genuine two-team games only - Pinnacle's matchups list is mostly
    "special" markets (props, futures, Yes/No propositions) sharing the
    same league and shape; those have no home/away alignment to resolve a
    team from and must not be treated as a game."""
    fixtures: dict[int, tuple[str, str, datetime | None]] = {}
    for matchup in matchups:
        if matchup.get("special") or matchup.get("type") != "matchup":
            continue
        participants = matchup.get("participants") or []
        home = next((p for p in participants if p.get("alignment") == "home"), None)
        away = next((p for p in participants if p.get("alignment") == "away"), None)
        if home is None or away is None or not home.get("name") or not away.get("name"):
            continue
        start_time = matchup.get("startTime")
        kickoff = (
            datetime.fromisoformat(str(start_time).replace("Z", "+00:00"))
            if start_time
            else None
        )
        fixtures[matchup["id"]] = (home["name"], away["name"], kickoff)
    return fixtures


_MARKET_TYPES = {"moneyline", "spread", "total"}


def _rows_for(market: dict[str, Any]) -> list[dict[str, Any]]:
    """One TeamMarketLine row per price in the market - Pinnacle's own
    `designation` ("home"|"away"|"over"|"under") already matches this
    schema's `side` values directly. `type` mostly does too
    ("moneyline"|"spread"|"total"), but Pinnacle also emits other market
    types on the same matchup (e.g. "team_total") that this schema's
    `market` column was never meant to carry (see its own `# spread|total|
    moneyline` comment in src/models/facts.py) - filtered out here rather
    than trusted wholesale."""
    if market.get("type") not in _MARKET_TYPES:
        return []
    rows: list[dict[str, Any]] = []
    for price in market.get("prices") or []:
        designation = price.get("designation")
        american = price.get("price")
        if designation is None or american is None:
            continue
        rows.append(
            {
                "market": market["type"],
                "side": designation,
                "line": price.get("points"),
                "price_american": int(american),
            }
        )
    return rows
