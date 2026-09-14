"""Underdog player props.

CONSTRAINT #17: the response is one document with five sibling arrays, and a
line names its player only through
line.over_under.appearance_stat.appearance_id -> appearances[].player_id ->
players[].id. That traversal lives in the preserved provider, verified
against 3,841 live lines, and is reused here rather than reimplemented.

Game appearances resolve through the provider's full matchup title and
scheduled time. Exact, unambiguous matches receive game IDs; series and
unresolved matches remain null.

Underdog's own provider already labels college-football rows "ncaaf" (its
`sport_id` is "CFB" - see underdog_api.py's _SPORT_ID_MAP), so supporting a
second sport here is exactly the filter change below, not new parsing.
"""

from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import text

from config.settings import get_settings
from src.data.providers.underdog_api import get_over_under_lines, raw_lines_to_props
from src.ingest.identity import resolve_player
from src.ingest.lines import record_prop_line
from src.ingest.prop_events import resolve_prop_event
from src.ingest.runs import record_run
from src.utils.normalize import normalize_stat_type
from src.services.quote_eligibility import withdraw_absent_props

SOURCE = "underdog"


async def ingest_props(db) -> tuple[int, int]:
    """Returns (rows_written, parked_count)."""
    supported = get_settings().supported_sports
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('underdog_full_snapshot'))"))
    poll_started = datetime.now(timezone.utc)

    written = 0
    parked = 0
    events = {}
    linked = 0

    async with record_run(db, SOURCE) as run:
        # Fetch failures must be visible in ingestion history. Do not refresh
        # or withdraw existing offers when the provider rejects the request.
        payload = await get_over_under_lines()
        rows = [row for row in raw_lines_to_props(payload) if row["sport"] in supported]
        for row in rows:
            external_id = row.get("underdog_player_id")
            if not external_id:
                parked += 1
                continue

            player = await resolve_player(
                db,
                source=SOURCE,
                external_id=external_id,
                full_name=row["player_name"],
                sport=row["sport"],
            )
            if player is None:
                # Unknown or ambiguous. Parked, never name-matched: two
                # active players are named Josh Allen and a wrong match
                # poisons the training set silently.
                parked += 1
                continue

            event = row.get('event')
            event_key = (row['sport'], str(event.get('id'))) if event else None
            if event_key is not None and event_key not in events:
                events[event_key] = await resolve_prop_event(db, row['sport'], event)
            game_id = events.get(event_key)
            if game_id is not None:
                linked += 1
            if await record_prop_line(
                db,
                player_id=player.id,
                game_id=game_id,
                stat_type=normalize_stat_type(row["raw_stat_type"]),
                line=row["line"],
                over_price_american=row["over_price_american"],
                under_price_american=row["under_price_american"],
                source=SOURCE,
            ):
                written += 1

        await withdraw_absent_props(db, SOURCE, poll_started)
        run.rows_written = written
        run.detail = f"{parked} appearances parked as unresolvable; {linked} props game-linked"
        await db.commit()
        return written, parked
