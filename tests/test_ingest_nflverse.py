"""nflverse historical ingestion.

Verified live on 2026-08-20: games.csv carries spread_line, total_line, and
both moneylines for 1999-2026, and the 2025 season is complete at 285/285
games with results and closing lines.
"""

from __future__ import annotations

from sqlalchemy import func, select

from src.ingest.nflverse import ingest_games
from src.models.facts import Game, TeamMarketLine
from src.models.identity import Team


async def test_ingest_2025_creates_285_games_with_closing_lines(db):
    written = await ingest_games(db, seasons=[2025])
    assert written > 0

    games = await db.scalar(select(func.count()).select_from(Game).where(Game.season == 2025))
    assert games == 285, f"expected the full 2025 season, got {games}"

    played = await db.scalar(
        select(func.count())
        .select_from(Game)
        .where(Game.season == 2025, Game.home_score.isnot(None))
    )
    assert played == 285, f"2025 is complete; {285 - played} games missing results"

    # Every game gets six closing rows: spread home/away, total over/under,
    # moneyline home/away.
    lines = await db.scalar(
        select(func.count())
        .select_from(TeamMarketLine)
        .where(TeamMarketLine.line_type == "closing")
    )
    assert lines == 285 * 6


async def test_exactly_32_teams_and_no_duplicates(db):
    await ingest_games(db, seasons=[2025])
    teams = await db.scalar(select(func.count()).select_from(Team))
    assert teams == 32, f"expected 32 NFL teams, got {teams}"


async def test_was_and_wsh_resolve_to_one_washington_team(db):
    """nfl.yaml maps both WAS and WSH to espn_id 28 - nflverse's Washington
    abbreviation changed across data vintages. Both must resolve to the
    same Team row or Team.espn_id's UNIQUE constraint breaks ingestion the
    moment both abbreviations appear across a multi-season pull."""
    from src.ingest.identity import resolve_team

    was = await resolve_team(db, "WAS")
    wsh = await resolve_team(db, "WSH")
    assert was.id == wsh.id
    assert was.espn_id == "28"


async def test_reingest_is_idempotent(db):
    await ingest_games(db, seasons=[2025])
    first = await db.scalar(select(func.count()).select_from(Game))
    await ingest_games(db, seasons=[2025])
    second = await db.scalar(select(func.count()).select_from(Game))
    assert first == second, "re-ingesting the same season duplicated games"


async def test_moneyline_rows_carry_no_line_value(db):
    """A moneyline has a price but no handicap. Storing 0.0 would make it
    indistinguishable from a pick-em spread."""
    await ingest_games(db, seasons=[2025])
    rows = await db.execute(
        select(TeamMarketLine.line).where(TeamMarketLine.market == "moneyline").limit(50)
    )
    assert all(value is None for (value,) in rows)


async def test_spread_sign_follows_the_sportsbook_convention(db):
    """The favourite's line is NEGATIVE.

    nflverse publishes the opposite sign (spread_line positive = home
    favoured), and ESPN publishes the opposite of nflverse. Storing either
    raw mixes conventions in one column with nothing raising an error. This
    test pins the convention using the game's own result as ground truth.
    """
    await ingest_games(db, seasons=[2025])

    # Find a decisively-decided game so the favourite is unambiguous.
    game = await db.scalar(
        select(Game)
        .where(
            Game.season == 2025,
            Game.home_score.isnot(None),
            (Game.home_score - Game.away_score) > 14,
        )
        .limit(1)
    )
    assert game is not None

    home_line = await db.scalar(
        select(TeamMarketLine.line).where(
            TeamMarketLine.game_id == game.id,
            TeamMarketLine.market == "spread",
            TeamMarketLine.side == "home",
        )
    )
    away_line = await db.scalar(
        select(TeamMarketLine.line).where(
            TeamMarketLine.game_id == game.id,
            TeamMarketLine.market == "spread",
            TeamMarketLine.side == "away",
        )
    )
    assert home_line is not None and away_line is not None
    assert home_line == -away_line, "the two sides must mirror each other"
    # A team that won by more than 14 was almost certainly favoured, and a
    # favourite's stored line is negative.
    assert home_line < 0, f"home won big but its stored line was {home_line}"


async def test_totals_are_identical_on_both_sides(db):
    """Over and under share one number; only the price differs."""
    await ingest_games(db, seasons=[2025])
    game = await db.scalar(select(Game).where(Game.season == 2025).limit(1))
    over = await db.scalar(
        select(TeamMarketLine.line).where(
            TeamMarketLine.game_id == game.id,
            TeamMarketLine.market == "total",
            TeamMarketLine.side == "over",
        )
    )
    under = await db.scalar(
        select(TeamMarketLine.line).where(
            TeamMarketLine.game_id == game.id,
            TeamMarketLine.market == "total",
            TeamMarketLine.side == "under",
        )
    )
    assert over == under
