"""One-off backfill: pull historical results and seed `teams` + `games`.

This is what `scripts/train_models.py` and `scripts/backtest.py` (Phase 3)
read their training data from. Run it once per sport before training, and
again whenever a new season needs to be added.

Usage:
    python -m scripts.seed_historical --sport nfl --seasons 2023 2024
    python -m scripts.seed_historical --sport nhl --seasons 20232024 20242025
    python -m scripts.seed_historical --sport nba --seasons 2023-24 2024-25
    python -m scripts.seed_historical --sport mlb --seasons 2023 2024
    python -m scripts.seed_historical --sport ncaaf --seasons 2023 2024

Uses `get_worker_db()` (constraint #1's NullPool entry point) rather than the
pooled API engine: this is a standalone batch process, not a long-lived
service holding an event loop, so it follows the same "own engine, own
lifecycle" rule Celery tasks follow.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.cache.db_client import get_worker_db
from src.models.orm import Game, Team
from src.utils.logging import get_logger

log = get_logger(__name__)


async def _get_or_create_team(db: AsyncSession, sport: str, name: str) -> str:
    result = await db.execute(select(Team.id).where(Team.sport == sport, Team.name == name))
    row = result.first()
    if row:
        return str(row[0])

    stmt = (
        pg_insert(Team)
        .values(sport=sport, name=name)
        .on_conflict_do_nothing(constraint="uq_team_sport_name")
        .returning(Team.id)
    )
    result = await db.execute(stmt)
    row = result.first()
    if row:
        return str(row[0])

    # Conflict raced us (another row inserted between the check and insert) -
    # re-select rather than error, since the row now exists either way.
    result = await db.execute(select(Team.id).where(Team.sport == sport, Team.name == name))
    return str(result.first()[0])


async def _seed_games(sport: str, games: list[dict[str, Any]]) -> int:
    seeded = 0
    async with get_worker_db() as db:
        for g in games:
            if not g.get("home_team_name") or not g.get("away_team_name"):
                continue
            home_id = await _get_or_create_team(db, sport, g["home_team_name"])
            away_id = await _get_or_create_team(db, sport, g["away_team_name"])

            # Historical games have no ESPN event id, so identity is
            # (sport, home, away, season) instead of `uq_game_espn`.
            conditions = [
                Game.sport == sport,
                Game.home_team_id == home_id,
                Game.away_team_id == away_id,
            ]
            season_value = g.get("season")
            if isinstance(season_value, int):
                conditions.append(Game.season == season_value)
            existing = await db.execute(select(Game.id).where(*conditions))
            if existing.first():
                continue

            db.add(
                Game(
                    sport=sport,
                    home_team_id=home_id,
                    away_team_id=away_id,
                    home_team_name=g["home_team_name"],
                    away_team_name=g["away_team_name"],
                    game_time=None,
                    status="final",
                    home_score=g.get("home_score"),
                    away_score=g.get("away_score"),
                    season=g.get("season") if isinstance(g.get("season"), int) else None,
                    week=g.get("week"),
                )
            )
            seeded += 1
        await db.commit()
    return seeded


async def run(sport: str, seasons: list[str]) -> None:
    games: list[dict[str, Any]] = []

    if sport == "nfl":
        from src.data.historical.nfl_loader import load_games

        games = load_games([int(s) for s in seasons])
    elif sport == "ncaaf":
        from src.data.historical.cfb_loader import load_games

        games = await load_games([int(s) for s in seasons])
    elif sport == "mlb" or sport == "ncaabaseball":
        from src.data.historical.mlb_loader import load_games

        for s in seasons:
            games.extend(load_games(int(s)))
    elif sport in ("nba", "wnba", "ncaam"):
        from src.data.historical.nba_loader import load_games

        for s in seasons:
            games.extend(await load_games(sport, s))
    elif sport == "nhl":
        from src.data.historical.nhl_loader import load_games

        for s in seasons:
            games.extend(await load_games(s))
    else:
        raise SystemExit(f"no historical loader for sport={sport}")

    log.info("seed_historical.loaded", sport=sport, count=len(games))
    seeded = await _seed_games(sport, games)
    log.info("seed_historical.seeded", sport=sport, count=seeded)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport", required=True)
    parser.add_argument("--seasons", nargs="+", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.sport, args.seasons))


if __name__ == "__main__":
    main()
