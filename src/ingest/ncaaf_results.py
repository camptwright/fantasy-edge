"""NCAAF outcomes share the durable retry and correction ledger."""
from src.ingest.nfl_results import sync_football_results


async def sync_ncaaf_results(db, limit=40):
    return await sync_football_results(db, 'ncaaf', limit)


async def backfill_prop_results(db, limit=50):
    # One cursor prevents duplicate confirmations across overlapping jobs.
    return await sync_football_results(db, 'ncaaf', limit)
