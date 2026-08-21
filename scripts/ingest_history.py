"""Offline historical ingestion. Runs on the training host, not CT100."""

from __future__ import annotations

import argparse
import asyncio

from src.db.client import get_worker_db
from src.ingest.nflverse import ingest_games
from src.ingest.players import ingest_player_stats, ingest_players


async def _run(seasons: list[int]) -> None:
    async with get_worker_db() as db:
        written = await ingest_games(db, seasons)
        print(f"ingested {written} closing-line rows across {len(seasons)} seasons")

        players_written = await ingest_players(db)
        print(f"ingested {players_written} new players")

        stats_written = await ingest_player_stats(db, seasons)
        print(f"ingested {stats_written} player-game stat rows across {len(seasons)} seasons")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", type=int, nargs="+", required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.seasons))


if __name__ == "__main__":
    main()
