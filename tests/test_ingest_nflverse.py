"""nflverse historical ingestion.

Verified live on 2026-08-20: games.csv carries spread_line, total_line, and
both moneylines for 1999-2026, and the 2025 season is complete at 285/285
games with results and closing lines.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from src.ingest.nflverse import _kickoff, ingest_games
from src.models.facts import Game, TeamMarketLine
from src.models.identity import Team


@pytest.mark.live
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


@pytest.mark.live
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


@pytest.mark.live
async def test_reingest_is_idempotent(db):
    await ingest_games(db, seasons=[2025])
    first_games = await db.scalar(select(func.count()).select_from(Game))
    first_lines = await db.scalar(select(func.count()).select_from(TeamMarketLine))

    await ingest_games(db, seasons=[2025])
    second_games = await db.scalar(select(func.count()).select_from(Game))
    second_lines = await db.scalar(select(func.count()).select_from(TeamMarketLine))

    assert first_games == second_games, "re-ingesting the same season duplicated games"
    # Fix 5 gave record_team_line's dedup key a line_type filter; the
    # closing-lines write path in ingest_games() has its own separate
    # already-exists guard (a `line_type == CLOSING` existence check), but
    # this is what actually proves re-ingestion doesn't duplicate the
    # TeamMarketLine rows themselves, not just the Game rows.
    assert first_lines == second_lines, "re-ingesting the same season duplicated market lines"


@pytest.mark.live
async def test_moneyline_rows_carry_no_line_value(db):
    """A moneyline has a price but no handicap. Storing 0.0 would make it
    indistinguishable from a pick-em spread."""
    await ingest_games(db, seasons=[2025])
    rows = await db.execute(
        select(TeamMarketLine.line).where(TeamMarketLine.market == "moneyline").limit(50)
    )
    assert all(value is None for (value,) in rows)


@pytest.mark.live
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


def test_kickoff_converts_eastern_to_utc_across_the_dst_boundary():
    """nflverse's gametime is Eastern LOCAL time, not UTC (its own data
    dictionary: "represented in 24-hour time and the Eastern time zone,
    regardless of what time zone the game was being played in"). A fixed
    offset is wrong because the season spans the November DST transition.

    Both cases below are pinned against nflreadpy.load_schedules()'s real
    gameday/gametime values (verified live 2026-08-22 via
    `nfl.load_schedules([2024, 2025])`), not against arithmetic assumed in
    a prompt:

      2025_01_DAL_PHI: gameday 2025-09-04, gametime "20:20" - the 2025
      season opener, a real 8:20 PM ET Thursday-night kickoff. September
      is EDT (UTC-4), so the correct UTC instant is 2025-09-05T00:20:00Z -
      one calendar day later than the naive UTC-stamped bug produced.

      2024_19_LAC_HOU: gameday 2025-01-11, gametime "16:30" - an AFC Wild
      Card game (season=2024, week=19 is nflverse's postseason
      convention). January is EST (UTC-5), a DIFFERENT offset from the
      September case, proving this isn't a single hardcoded offset.
    """
    opener = _kickoff({"gameday": "2025-09-04", "gametime": "20:20"})
    assert opener == datetime(2025, 9, 5, 0, 20, tzinfo=timezone.utc)

    wildcard = _kickoff({"gameday": "2025-01-11", "gametime": "16:30"})
    assert wildcard == datetime(2025, 1, 11, 21, 30, tzinfo=timezone.utc)


@pytest.mark.live
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
