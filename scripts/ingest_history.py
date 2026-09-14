"""Offline historical ingestion. Runs on the training host, not the app's
own deployment host (the Mac mini; formerly CT100, now decommissioned).

--sport nfl (default): nflverse - games, player identity, and player-game
stats in one pass, needs the `[offline]` extras (nflreadpy).

--sport ncaaf: player-game stats only, from ESPN's per-game boxscore
(src/ingest/ncaaf_player_stats.py) - no nflverse equivalent exists for
college football. Games and player identity are NOT re-ingested here:
games already come from src/ingest/espn.py's live sync/backfill, and
players from scripts/seed_players.py - both need to have already run.
"""

from __future__ import annotations

import argparse
import asyncio

from src.db.client import get_worker_db
from src.ingest.ncaaf_player_stats import ingest_player_stats as ingest_ncaaf_player_stats
from src.ingest.nflverse import ingest_games
from src.ingest.nfl_pbp_props import ingest_longest_props
from src.ingest.players import ingest_player_stats, ingest_players


async def _run_nfl(seasons: list[int], with_play_props: bool) -> None:
    async with get_worker_db() as db:
        written = await ingest_games(db, seasons)
        print(f"ingested {written} closing-line rows across {len(seasons)} seasons")

        players_written = await ingest_players(db)
        print(f"ingested {players_written} new players")

        stats_written = await ingest_player_stats(db, seasons)
        print(f"ingested {stats_written} player-game stat rows across {len(seasons)} seasons")
        if with_play_props:
            longest_written = await ingest_longest_props(db, seasons)
            print(f"ingested {longest_written} longest-play player-game stat rows across {len(seasons)} seasons")


async def _run_ncaaf(seasons: list[int]) -> None:
    async with get_worker_db() as db:
        stats_written = await ingest_ncaaf_player_stats(db, seasons)
        print(f"ingested {stats_written} NCAAF player-game stat rows across {len(seasons)} seasons")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", choices=["nfl", "ncaaf"], default="nfl")
    parser.add_argument("--seasons", type=int, nargs="+", required=True)
    parser.add_argument("--with-play-props", action="store_true",
                        help="offline nflverse PBP backfill for longest rush/reception outcomes")
    args = parser.parse_args()
    if args.sport == "nfl":
        asyncio.run(_run_nfl(args.seasons, args.with_play_props))
    else:
        asyncio.run(_run_ncaaf(args.seasons))


if __name__ == "__main__":
    main()
