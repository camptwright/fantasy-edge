"""Offline historical ingestion. Runs on the training host, not CT100."""

from __future__ import annotations

import argparse
import asyncio

from src.db.client import get_worker_db
from src.ingest.nflverse import ingest_games


async def _run(seasons: list[int]) -> None:
    async with get_worker_db() as db:
        written = await ingest_games(db, seasons)
        print(f"ingested {written} closing-line rows across {len(seasons)} seasons")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seasons", type=int, nargs="+", required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.seasons))


if __name__ == "__main__":
    main()
