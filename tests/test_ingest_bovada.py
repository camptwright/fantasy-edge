"""src/ingest/bovada.py against a real (trimmed) live response.

Fixture captured live 2026-09-03 (tests/fixtures/bovada_nfl.json): two
events, only one of which has a locally-seeded Game to match against, to
prove an unmatched event is skipped rather than raising.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from src.ingest.bovada import _parse_american, poll_team_markets
from src.ingest.identity import resolve_team
from src.models.facts import Game, TeamMarketLine

FIXTURES = Path(__file__).parent / "fixtures"
PAYLOAD = json.loads((FIXTURES / "bovada_nfl.json").read_text())


async def test_matched_event_writes_all_three_markets_with_correct_sign(db):
    home = await resolve_team(db, "Seattle Seahawks", sport="nfl")
    away = await resolve_team(db, "New England Patriots", sport="nfl")
    game = Game(
        season=2026, week=1, status="scheduled",
        home_team_id=home.id, away_team_id=away.id,
        game_time=datetime(2026, 9, 9, 20, 20, tzinfo=timezone.utc),
    )
    db.add(game)
    await db.flush()

    with patch(
        "src.ingest.bovada.BovadaScraper.fetch_json", new=AsyncMock(return_value=PAYLOAD)
    ):
        written = await poll_team_markets(db, sport="nfl")

    assert written == 6  # moneyline + spread (home/away) + total (over/under)

    rows = (
        await db.execute(select(TeamMarketLine).where(TeamMarketLine.game_id == game.id))
    ).scalars().all()
    by_market_side = {(r.market, r.side): r for r in rows}

    # SIGN: Seahawks (home) favoured by 3.5 - verified live against Bovada's
    # own price.handicap, already in this app's storage convention.
    assert by_market_side[("spread", "home")].line == -3.5
    assert by_market_side[("spread", "home")].price_american == -110
    assert by_market_side[("spread", "away")].line == 3.5

    assert by_market_side[("moneyline", "home")].price_american == -185
    assert by_market_side[("moneyline", "away")].price_american == 160

    assert by_market_side[("total", "over")].line == 44.0
    assert by_market_side[("total", "under")].line == 44.0


async def test_event_with_no_matching_game_is_skipped_not_errored(db):
    """Neither fixture event has a seeded Game here - both must be skipped
    cleanly rather than raising (e.g. on a None game_id insert)."""
    with patch(
        "src.ingest.bovada.BovadaScraper.fetch_json", new=AsyncMock(return_value=PAYLOAD)
    ):
        written = await poll_team_markets(db, sport="nfl")

    assert written == 0


async def test_unsupported_sport_is_a_noop_without_any_request(db):
    with patch("src.ingest.bovada.BovadaScraper.fetch_json", new=AsyncMock()) as fetch:
        written = await poll_team_markets(db, sport="wnba")

    assert written == 0
    fetch.assert_not_awaited()


async def test_a_referer_and_origin_are_always_sent(db):
    """Found live 2026-09-04: a header-less request (TLS impersonation
    alone) started coming back as a zero-event response from Bovada's
    Cloudflare front after enough repeated requests from one IP, while a
    request carrying a realistic Referer/Origin kept succeeding. This pins
    that those headers are actually sent, not just present in a docstring."""
    with patch(
        "src.ingest.bovada.BovadaScraper.fetch_json", new=AsyncMock(return_value=[{"events": []}])
    ) as fetch:
        await poll_team_markets(db, sport="nfl")

    _, kwargs = fetch.call_args
    assert "Referer" in kwargs["headers"]
    assert "Origin" in kwargs["headers"]


def test_even_money_is_parsed_as_plus_100():
    """Found live 2026-09-03: Bovada prints exact even-money prices as the
    literal string "EVEN" rather than "+100" - a bare int() on that string
    raises ValueError and would have crashed the whole event's parsing."""
    assert _parse_american("EVEN") == 100


def test_ordinary_prices_still_parse():
    assert _parse_american("-110") == -110
    assert _parse_american("+160") == 160


def test_unparseable_price_returns_none_rather_than_raising():
    assert _parse_american(None) is None
    assert _parse_american("garbage") is None
