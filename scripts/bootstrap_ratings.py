"""Offline Elo bootstrap. Runs on the training host, not reekserver-1.

NFL: nflverse historical games (already ingested via scripts/ingest_history.py
into the `games` table) never pass through src/ingest/espn.py's live-sync Elo
hook, so this walks them chronologically and applies the same
update_ratings_after_game() directly.

NCAAF and NBA: neither has an nflverse-equivalent historical source (see
docs/nfl-modeling.md), so both instead re-run sync_scoreboard() against past
season dates - the same insert-on-change path live sync uses, which already
carries the Elo hook, so their ratings build as a side effect of the
backfill itself rather than a second code path.

MLB and NHL: same idea, but re-run src/ingest/mlb.py's / src/ingest/nhl.py's
own sync_schedule() (each sport's official API) instead of ESPN, matching
those sources' own primary-schedule role in live sync (config/settings.py's
espn_sports).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta

from sqlalchemy import select

from src.db.client import get_worker_db
from src.ingest.espn import sync_scoreboard
from src.ingest.mlb import sync_schedule as sync_mlb_schedule
from src.ingest.nhl import sync_schedule as sync_nhl_schedule
from src.models.facts import Game
from src.services.elo import update_ratings_after_game


async def _bootstrap_nfl(seasons: list[int]) -> int:
    updated = 0
    async with get_worker_db() as db:
        games = (
            await db.execute(
                select(Game)
                .where(
                    Game.sport == "nfl",
                    Game.season.in_(seasons),
                    Game.home_score.isnot(None),
                    Game.away_score.isnot(None),
                )
                .order_by(Game.game_time.asc().nulls_last())
            )
        ).scalars()
        for game in games:
            await update_ratings_after_game(db, game)
            updated += 1
        await db.commit()
    return updated


async def _bootstrap_ncaaf(seasons: list[int]) -> None:
    """Weekly date windows, not one season-wide range - see sync_scoreboard's
    own docstring on why. Regular season runs late August through early
    December; conference championships and bowls run through early January
    of the following year."""
    async with get_worker_db() as db:
        for season in seasons:
            start = date(season, 8, 20)
            end = date(season + 1, 1, 20)
            current = start
            while current <= end:
                await sync_scoreboard(db, sport="ncaaf", dates=f"{current:%Y%m%d}")
                current += timedelta(days=7)


async def _bootstrap_nba(seasons: list[int]) -> None:
    """`seasons` is the year a season STARTS in (e.g. 2025 for the 2025-26
    season), matching ESPN's own season.year for an October-started season
    rather than nflverse's single-calendar-year NFL convention. Regular
    season runs late October through mid-April; playoffs run into late
    June, so the window extends into the following calendar year like
    NCAAF's does.

    Daily, NOT weekly like _bootstrap_ncaaf's 7-day stride: NCAAF is almost
    entirely a Saturday sport, so sampling one aligned day per week still
    catches nearly every game; the NBA plays every night of the week, so
    the same stride would silently skip roughly six sevenths of the
    season's games."""
    async with get_worker_db() as db:
        for season in seasons:
            start = date(season, 10, 15)
            end = date(season + 1, 6, 25)
            current = start
            while current <= end:
                await sync_scoreboard(db, sport="nba", dates=f"{current:%Y%m%d}")
                current += timedelta(days=1)


async def _bootstrap_mlb(seasons: list[int]) -> None:
    """One request per season, not a daily/weekly loop like the ESPN-backed
    sports above - verified live 2026-09-04 that MLB Stats API's own
    /schedule endpoint returns a full season (spring training through
    World Series, ~2,650 games) in a single call with no pagination, unlike
    ESPN's own scoreboard endpoint (sync_scoreboard's docstring: "ESPN's
    own range support is undocumented and unreliable beyond roughly a
    week"). `seasons` is the calendar year here, matching MLB's own
    single-season convention (unlike NBA's October-start numbering)."""
    async with get_worker_db() as db:
        for season in seasons:
            await sync_mlb_schedule(
                db, start_date=f"{season}-02-15", end_date=f"{season}-11-15"
            )


async def _bootstrap_nhl(seasons: list[int]) -> None:
    """sync_schedule() already chains /schedule/{date}'s own nextStartDate
    internally (one call per 7-day window) up to `days_ahead` - one
    top-level call per season here, not a manual date-stepping loop like
    NBA's. `seasons` is the year a season STARTS in, matching NHL's own
    convention (season 20252026 for the 2025-26 season) the same way NBA's
    October-start numbering works. Regular season runs early October
    through mid-April; playoffs run into late June."""
    async with get_worker_db() as db:
        for season in seasons:
            start = date(season, 10, 1)
            end = date(season + 1, 6, 25)
            await sync_nhl_schedule(db, start_date=f"{start:%Y-%m-%d}", days_ahead=(end - start).days)


async def _run(seasons: list[int]) -> None:
    nfl_updated = await _bootstrap_nfl(seasons)
    print(f"applied {nfl_updated} NFL Elo updates across seasons {seasons}")

    await _bootstrap_ncaaf(seasons)
    print(f"backfilled NCAAF scoreboard (and Elo) across seasons {seasons}")

    await _bootstrap_nba(seasons)
    print(f"backfilled NBA scoreboard (and Elo) across seasons {seasons}")

    await _bootstrap_mlb(seasons)
    print(f"backfilled MLB scoreboard (and Elo) across seasons {seasons}")

    await _bootstrap_nhl(seasons)
    print(f"backfilled NHL scoreboard (and Elo) across seasons {seasons}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", type=int, nargs="+", required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.seasons))


if __name__ == "__main__":
    main()
