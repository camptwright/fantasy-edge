"""Quota-guarded team-market polling from The Odds API.

CONSTRAINT #4: three defences, all from day one - season-aware polling,
generous intervals, and this quota guard reading x-requests-remaining. The
free tier allows 500 requests per month; below a configured floor of
remaining requests, the guard sets a Redis key with a 24h TTL that
suppresses all further polling until it expires.

CONSTRAINT #22: the quota helpers below take an explicit `redis` client
parameter rather than reaching for a module-level cached one. That is what
keeps them correct from both the FastAPI process (one persistent event
loop) and a Celery task (fresh event loop per invocation) - do not add a
global/cached Redis client here.

Verified 2026-08-21 against a live fixture (tests/fixtures/theodds_nfl.json,
one request against the 500/month budget): the historical endpoint is
restricted to paid plans and billed at ten times the cost of current odds,
so this module polls current odds only. Player props are billed per
market-region combination and are not fetched here; Underdog is the props
source.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.ingest.identity import resolve_team
from src.ingest.lines import record_team_line
from src.ingest.runs import record_run
from src.models.facts import Game

SOURCE = "theodds"
QUOTA_KEY = "odds_api:quota_exhausted"
QUOTA_TTL_SECONDS = 86400


async def is_quota_exhausted(redis: Redis) -> bool:
    return await redis.exists(QUOTA_KEY) == 1


async def set_quota_exhausted(redis: Redis) -> None:
    await redis.set(QUOTA_KEY, "1", ex=QUOTA_TTL_SECONDS)


async def clear_quota_exhausted(redis: Redis) -> None:
    await redis.delete(QUOTA_KEY)


async def poll_team_markets(db: AsyncSession, redis: Redis) -> int:
    """Poll h2h, spreads, and totals. Returns rows written."""
    settings = get_settings()
    if not settings.odds_api_key:
        return 0
    if await is_quota_exhausted(redis):
        return 0

    async with record_run(db, SOURCE) as run:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{settings.odds_api_base_url}/sports/americanfootball_nfl/odds",
                params={
                    "apiKey": settings.odds_api_key,
                    "regions": "us",
                    "markets": "h2h,spreads,totals",
                    "oddsFormat": "american",
                },
            )
            remaining = response.headers.get("x-requests-remaining")
            if remaining is not None and int(remaining) < settings.odds_api_quota_floor:
                await set_quota_exhausted(redis)
                run.detail = f"quota guard tripped at {remaining} remaining"
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # httpx.HTTPStatusError's message embeds the full request
                # URL, including the apiKey query parameter - letting it
                # propagate unchanged would write the live API key straight
                # into ingestion_runs.detail, an ordinary application table
                # with no secret protection, on any failed request (a bad
                # key, rate limiting, a transient 5xx). `from None` also
                # severs exception chaining so nothing downstream can
                # recover the original exception's request/URL via
                # __cause__/__context__.
                raise RuntimeError(
                    f"Odds API request failed: {exc.response.status_code}"
                ) from None
            events = response.json()

        for event in events:
            game = await _match_game(db, event)
            if game is None:
                continue
            for entry in _rows_for(event):
                if await record_team_line(
                    db, game_id=game.id, source=SOURCE, line_type="live", **entry
                ):
                    run.rows_written += 1
        await db.commit()
        return run.rows_written


async def _match_game(db: AsyncSession, event: dict[str, Any]) -> Game | None:
    """The Odds API identifies teams by full display name, not abbreviation."""
    home_name, away_name = event.get("home_team"), event.get("away_team")
    commence = event.get("commence_time")
    if not home_name or not away_name or not commence:
        return None

    try:
        home = await resolve_team(db, home_name)
        away = await resolve_team(db, away_name)
    except LookupError:
        return None
    kickoff = datetime.fromisoformat(str(commence).replace("Z", "+00:00"))

    # CONSTRAINT #2: game_time is nullable, so a bare range comparison would
    # silently drop fixtures published without a kickoff time. Match on the
    # team pair first and only narrow by time when both sides have one.
    candidates = list(
        (
            await db.execute(
                select(Game).where(
                    Game.home_team_id == home.id, Game.away_team_id == away.id
                )
            )
        ).scalars()
    )
    if not candidates:
        return None
    timed = [
        game
        for game in candidates
        if game.game_time is not None
        and abs((game.game_time - kickoff).total_seconds()) < 86400
    ]
    if timed:
        return timed[0]
    return candidates[0] if len(candidates) == 1 else None


def _rows_for(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten one event's bookmaker blocks into line rows.

    Response shape: event.bookmakers[].markets[].outcomes[], where an outcome
    carries `name`, `price`, and - for spreads and totals - `point`. Team
    outcomes are named by full team name; totals outcomes are named Over and
    Under.

    Only the first bookmaker is taken. Storing every book would multiply row
    volume without helping: this feed exists to corroborate ESPN, and a
    consensus across books is a modelling decision for Plan 2, not an
    ingestion one.

    SIGN: verified 2026-08-21 against a live fixture
    (tests/fixtures/theodds_nfl.json, event 0 - Seahawks -3.5/-185 favourite
    over the Patriots +3.5/+154). The Odds API publishes each side's own
    handicap already in sportsbook convention - the favourite's `point` is
    negative - which matches the storage convention directly, so no
    negation is applied here.
    """
    bookmakers = event.get("bookmakers") or []
    if not bookmakers:
        return []

    home_name, away_name = event.get("home_team"), event.get("away_team")
    rows: list[dict[str, Any]] = []

    for market in bookmakers[0].get("markets") or []:
        key = market.get("key")
        for outcome in market.get("outcomes") or []:
            name = outcome.get("name")
            price = outcome.get("price")
            point = outcome.get("point")

            if key == "h2h" and name in (home_name, away_name):
                rows.append({
                    "market": "moneyline",
                    "side": "home" if name == home_name else "away",
                    "line": None,
                    "price_american": None if price is None else int(price),
                })
            elif key == "spreads" and name in (home_name, away_name):
                rows.append({
                    "market": "spread",
                    "side": "home" if name == home_name else "away",
                    "line": None if point is None else float(point),
                    "price_american": None if price is None else int(price),
                })
            elif key == "totals" and name in ("Over", "Under"):
                rows.append({
                    "market": "total",
                    "side": name.lower(),
                    "line": None if point is None else float(point),
                    "price_american": None if price is None else int(price),
                })
    return rows
