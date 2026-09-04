"""src/ingest/pinnacle.py against a real (trimmed) live response pair.

Fixtures captured live 2026-09-03 (tests/fixtures/pinnacle_nfl_matchups.json,
pinnacle_nfl_markets.json): matchups holds one genuine two-team game (Rams
home, 49ers away) plus one "special" (Team to Make Playoffs) to prove
specials are excluded; markets holds every alternate line Pinnacle published
for that one matchup, to prove only the isAlternate=false primary line
survives.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from src.ingest.identity import resolve_team
from src.ingest.pinnacle import poll_team_markets
from src.models.facts import Game, TeamMarketLine

FIXTURES = Path(__file__).parent / "fixtures"
MATCHUPS = json.loads((FIXTURES / "pinnacle_nfl_matchups.json").read_text())
MARKETS = json.loads((FIXTURES / "pinnacle_nfl_markets.json").read_text())


async def _seed_game(db) -> Game:
    home = await resolve_team(db, "Los Angeles Rams", sport="nfl")
    away = await resolve_team(db, "San Francisco 49ers", sport="nfl")
    game = Game(
        season=2026, week=2, status="scheduled",
        home_team_id=home.id, away_team_id=away.id,
        game_time=datetime(2026, 9, 11, 0, 35, tzinfo=timezone.utc),
    )
    db.add(game)
    await db.flush()
    return game


async def test_only_the_primary_line_is_written_for_the_matched_game(db):
    game = await _seed_game(db)

    with patch(
        "src.ingest.pinnacle.PinnacleScraper.fetch_json",
        new=AsyncMock(side_effect=[MATCHUPS, MARKETS]),
    ):
        written = await poll_team_markets(db, sport="nfl")

    # moneyline (home/away) + primary spread (home/away) + primary total
    # (over/under) = 6 rows. Every alternate spread/total line and the
    # "team_total" market type are excluded.
    assert written == 6

    rows = (
        await db.execute(select(TeamMarketLine).where(TeamMarketLine.game_id == game.id))
    ).scalars().all()
    by_market_side = {(r.market, r.side): r for r in rows}

    assert set(by_market_side) == {
        ("moneyline", "home"), ("moneyline", "away"),
        ("spread", "home"), ("spread", "away"),
        ("total", "over"), ("total", "under"),
    }

    # SIGN: verified live - Rams (home) favoured by 3.5, so home's spread
    # is stored negative, matching this app's storage convention.
    assert by_market_side[("spread", "home")].line == -3.5
    assert by_market_side[("spread", "home")].price_american == -113
    assert by_market_side[("spread", "away")].line == 3.5
    assert by_market_side[("spread", "away")].price_american == 100

    assert by_market_side[("moneyline", "home")].price_american == -211
    assert by_market_side[("moneyline", "away")].price_american == 182

    assert by_market_side[("total", "over")].line == 48.0
    assert by_market_side[("total", "under")].line == 48.0


async def test_the_special_matchup_never_produces_a_team_market_line(db):
    """The "Team to Make Playoffs" entry in the fixture has no home/away
    alignment - if it were ever mistaken for a game, resolving a team from
    it would raise or misattribute, not silently do nothing. This proves it
    is filtered out before any team resolution is attempted."""
    await _seed_game(db)

    with patch(
        "src.ingest.pinnacle.PinnacleScraper.fetch_json",
        new=AsyncMock(side_effect=[MATCHUPS, MARKETS]),
    ):
        # Must not raise despite the special entry being present.
        written = await poll_team_markets(db, sport="nfl")

    assert written == 6  # unchanged from the real-game-only count above


async def test_unsupported_sport_is_a_noop_without_any_request(db):
    with patch(
        "src.ingest.pinnacle.PinnacleScraper.fetch_json", new=AsyncMock()
    ) as fetch:
        written = await poll_team_markets(db, sport="wnba")

    assert written == 0
    fetch.assert_not_awaited()
