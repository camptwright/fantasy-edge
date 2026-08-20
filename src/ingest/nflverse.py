"""Historical NFL fixtures, results, and closing team lines from nflverse.

nflreadpy returns Polars frames and pulls in a heavy dependency chain, so it
is imported lazily and lives in the `offline` optional group - the serving
image must not carry it.

Verified live 2026-08-20: games.csv spans 1999-2026 and carries spread_line,
total_line, home_moneyline, away_moneyline, home_spread_odds,
away_spread_odds, over_odds, and under_odds. The 2025 season is complete at
285/285 games.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingest.identity import resolve_team
from src.ingest.runs import record_run
from src.models.facts import Game, TeamMarketLine

CLOSING = "closing"
SOURCE = "nflverse"


def _nflreadpy() -> Any:
    try:
        import nflreadpy as nfl  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - offline envs only
        raise RuntimeError(
            "historical ingestion requires nflreadpy; "
            "install with pip install 'fantasy-edge[offline]'"
        ) from exc
    return nfl


def _records(frame: Any) -> list[dict[str, Any]]:
    """Convert a Polars frame without making Polars a runtime dependency."""
    if hasattr(frame, "to_dicts"):
        return list(frame.to_dicts())
    return list(frame)


def _number(value: Any) -> float | None:
    if value is None or value == "" or value == "NA":
        return None
    return float(value)


def _kickoff(record: dict[str, Any]) -> datetime | None:
    """CONSTRAINT #2: game_time stays null when the source has no time."""
    gameday = record.get("gameday")
    if not gameday:
        return None
    gametime = record.get("gametime")
    if not gametime:
        return datetime.combine(
            datetime.fromisoformat(str(gameday)).date(), time(0, 0), tzinfo=timezone.utc
        )
    hour, minute = (int(part) for part in str(gametime).split(":")[:2])
    return datetime.combine(
        datetime.fromisoformat(str(gameday)).date(),
        time(hour, minute),
        tzinfo=timezone.utc,
    )


def _closing_lines(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Six rows per game: spread home/away, total over/under, moneyline both.

    A moneyline carries a price but no handicap, so its `line` stays None -
    storing 0.0 would be indistinguishable from a pick-em spread.

    SIGN: nflverse spread_line is POSITIVE when the home team is favoured
    (confirmed in nflreadr's schedules dictionary: "A positive number means
    the home team was favored by that many points"). The storage convention
    is the sportsbook one, where a favourite's line is negative, so the home
    line is the NEGATION of spread_line.
    """
    spread = _number(record.get("spread_line"))
    total = _number(record.get("total_line"))
    return [
        {"market": "spread", "side": "home",
         "line": None if spread is None else -spread,
         "price": _number(record.get("home_spread_odds"))},
        {"market": "spread", "side": "away",
         "line": spread,
         "price": _number(record.get("away_spread_odds"))},
        {"market": "total", "side": "over", "line": total,
         "price": _number(record.get("over_odds"))},
        {"market": "total", "side": "under", "line": total,
         "price": _number(record.get("under_odds"))},
        {"market": "moneyline", "side": "home", "line": None,
         "price": _number(record.get("home_moneyline"))},
        {"market": "moneyline", "side": "away", "line": None,
         "price": _number(record.get("away_moneyline"))},
    ]


async def ingest_games(db: AsyncSession, seasons: list[int]) -> int:
    """Upsert fixtures, results, and closing lines. Returns rows written."""
    nfl = _nflreadpy()
    records = _records(nfl.load_schedules(seasons))

    async with record_run(db, SOURCE) as run:
        for record in records:
            nflverse_id = record.get("game_id")
            if not nflverse_id:
                continue

            game = await db.scalar(
                select(Game).where(Game.nflverse_game_id == nflverse_id)
            )
            if game is None:
                game = Game(nflverse_game_id=nflverse_id)
                db.add(game)

            # Set the team-independent fields (including the NOT NULL season
            # column) before resolving teams below. resolve_team() issues a
            # SELECT, which triggers autoflush on this session; if the new
            # Game row is still bare at that point, Postgres rejects the
            # premature INSERT with a NOT NULL violation on season.
            game.season = int(record["season"])
            game.week = int(record["week"]) if record.get("week") is not None else None
            game.game_type = record.get("game_type")
            game.game_time = _kickoff(record)
            game.home_rest = record.get("home_rest")
            game.away_rest = record.get("away_rest")
            game.div_game = bool(record["div_game"]) if record.get("div_game") is not None else None
            game.roof = record.get("roof")
            game.surface = record.get("surface")
            game.temp = _number(record.get("temp"))
            game.wind = _number(record.get("wind"))

            home = await resolve_team(db, record["home_team"])
            away = await resolve_team(db, record["away_team"])
            game.home_team_id = home.id
            game.away_team_id = away.id

            home_score = record.get("home_score")
            away_score = record.get("away_score")
            if home_score is not None and away_score is not None:
                game.home_score = int(home_score)
                game.away_score = int(away_score)
                game.status = "final"
            await db.flush()

            already = await db.scalar(
                select(TeamMarketLine.id).where(
                    TeamMarketLine.game_id == game.id,
                    TeamMarketLine.source == SOURCE,
                    TeamMarketLine.line_type == CLOSING,
                ).limit(1)
            )
            if already is not None:
                continue

            for entry in _closing_lines(record):
                db.add(
                    TeamMarketLine(
                        game_id=game.id,
                        market=entry["market"],
                        side=entry["side"],
                        line=entry["line"],
                        price_american=None if entry["price"] is None else int(entry["price"]),
                        source=SOURCE,
                        line_type=CLOSING,
                        observed_at=game.game_time or datetime.now(timezone.utc),
                    )
                )
                run.rows_written += 1
        await db.commit()
        return run.rows_written
