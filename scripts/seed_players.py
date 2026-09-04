"""Occasional non-NFL player-identity seeding, run manually - like
scripts/ingest_history.py, this is not on any Celery schedule (neither is
NFL's own equivalent, src/ingest/players.py's ingest_players). Run once per
season, or after a large roster shakeup, to unpark Underdog/PrizePicks
props for a sport that previously had zero seeded players.
"""

from __future__ import annotations

import argparse
import asyncio

from src.db.client import get_worker_db
from src.ingest.mlb_players import ingest_players as ingest_mlb_players
from src.ingest.ncaaf_players import ingest_players as ingest_ncaaf_players


async def _run(sports: list[str]) -> None:
    async with get_worker_db() as db:
        if "ncaaf" in sports:
            written = await ingest_ncaaf_players(db)
            print(f"ingested {written} new NCAAF players")
        if "mlb" in sports:
            written = await ingest_mlb_players(db)
            print(f"ingested {written} new MLB players")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sports", nargs="+", choices=["ncaaf", "mlb"], required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.sports))


if __name__ == "__main__":
    main()
