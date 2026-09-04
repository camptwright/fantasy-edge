"""Bovada's public coupon JSON.

Offshore book, no US state licensing - unlike DraftKings/FanDuel/BetMGM
(legal-state-only, and unreachable by design from a non-legal-state IP; see
DEPLOYMENT.md), Bovada's odds endpoint is reachable from anywhere. Fronted
by Cloudflare, so this needs curl_cffi's TLS impersonation rather than plain
httpx - a bare `requests`-style client gets blocked outright.

SIGN: verified live 2026-09-03 (Patriots @ Seahawks, Seahawks -3.5 home
favourite) - Bovada's own `price.handicap` on each spread/total outcome
already matches this app's storage convention (home's handicap negative
when favoured), so no negation is applied here, same as theodds.py/
pinnacle.py's equivalent notes.

Only the "Game Lines" display group's markets are read (`defaultType: true`,
`period.main: true`) - Bovada nests alternate lines, first-half lines, and
player props in separate displayGroups on the same event, and reading every
group would multiply this schema's one-row-per-side-per-market shape into
duplicates at different lines, the same problem Pinnacle's `isAlternate`
flag solves there.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.data.scrapers.base import BaseScraper, ScraperError
from src.ingest.games import find_game_by_teams
from src.ingest.identity import resolve_team
from src.ingest.lines import record_team_line
from src.ingest.runs import record_run

SOURCE = "bovada"

_MARKET_TYPES = {"2W-HCAP": "spread", "2W-12": "moneyline", "2W-OU": "total"}
_SIDE_TYPES = {"H": "home", "A": "away", "O": "over", "U": "under"}


def _parse_american(price: str) -> int | None:
    """Bovada prints exact even-money prices as the literal string "EVEN"
    rather than "+100" - found live 2026-09-03 (test_ingest_bovada_live.py),
    not documented anywhere. +100 is the standard American-odds
    representation of even money."""
    if price == "EVEN":
        return 100
    try:
        return int(price)
    except (TypeError, ValueError):
        return None


class BovadaScraper(BaseScraper):
    source = SOURCE
    min_interval = 2.0


def _headers(path: str) -> dict[str, str]:
    """TLS impersonation alone (BaseScraper's default) is not always
    enough for Bovada's Cloudflare front - found live 2026-09-04 after this
    poller had already worked bare once: a second day of repeated
    header-less requests from the same IP started coming back as a
    zero-event `{}`/empty-events response, while a request carrying a
    realistic Referer/Origin/Accept kept succeeding throughout. Matches the
    research doc's own guidance that a consistent, coherent browser
    fingerprint - not just TLS - is what a Cloudflare-fronted site actually
    checks."""
    return {
        "Referer": f"https://www.bovada.lv/sports/{path}",
        "Origin": "https://www.bovada.lv",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }


async def poll_team_markets(db: AsyncSession, sport: str = "nfl") -> int:
    """Poll moneyline/spread/total for one sport. Returns rows written."""
    settings = get_settings()
    path = settings.bovada_sport_paths.get(sport)
    if path is None:
        return 0

    scraper = BovadaScraper()
    async with record_run(db, f"{SOURCE}_{sport}") as run:
        try:
            payload = await scraper.fetch_json(
                f"{settings.bovada_base_url}/{path}",
                headers=_headers(path),
                params={"marketFilterId": "def", "preMatchOnly": "true", "lang": "en"},
            )
        except ScraperError as exc:
            run.detail = str(exc)
            raise RuntimeError(str(exc)) from None

        events = payload[0].get("events", []) if payload else []
        for event in events:
            game = await _match_event(db, event, sport)
            if game is None:
                continue
            for row in _rows_for(event):
                if await record_team_line(
                    db, game_id=game.id, source=SOURCE, line_type="live", **row
                ):
                    run.rows_written += 1
        await db.commit()
        return run.rows_written


async def _match_event(db: AsyncSession, event: dict[str, Any], sport: str):
    competitors = event.get("competitors") or []
    home = next((c for c in competitors if c.get("home") is True), None)
    away = next((c for c in competitors if c.get("home") is False), None)
    start_time = event.get("startTime")
    if home is None or away is None or not home.get("name") or not away.get("name"):
        return None
    try:
        home_team = await resolve_team(db, home["name"], sport=sport)
        away_team = await resolve_team(db, away["name"], sport=sport)
    except LookupError:
        return None
    # Bovada's startTime is epoch milliseconds, not ISO8601.
    kickoff = (
        datetime.fromtimestamp(start_time / 1000, tz=timezone.utc)
        if start_time is not None
        else None
    )
    return await find_game_by_teams(
        db, home_team_id=home_team.id, away_team_id=away_team.id, kickoff=kickoff
    )


def _rows_for(event: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in event.get("displayGroups") or []:
        if not group.get("defaultType"):
            continue
        for market in group.get("markets") or []:
            market_type = _MARKET_TYPES.get(market.get("key"))
            if (
                market_type is None
                or not market.get("period", {}).get("main")
                or market.get("status") != "O"
            ):
                continue
            for outcome in market.get("outcomes") or []:
                side = _SIDE_TYPES.get(outcome.get("type"))
                price = outcome.get("price") or {}
                american = _parse_american(price.get("american"))
                if side is None or american is None:
                    continue
                handicap = price.get("handicap")
                rows.append(
                    {
                        "market": market_type,
                        "side": side,
                        "line": float(handicap) if handicap is not None else None,
                        "price_american": american,
                    }
                )
    return rows
