"""Underdog player props.

CONSTRAINT #17: the response is one document with five sibling arrays, and a
line names its player only through
line.over_under.appearance_stat.appearance_id -> appearances[].player_id ->
players[].id. That traversal lives in the preserved provider, verified
against 3,841 live lines, and is reused here rather than reimplemented.

There is no teams array, so a prop's game cannot be resolved from this
payload. game_id is left null; joining props to fixtures is a later concern
and guessing it here would attach lines to the wrong game.
"""

from __future__ import annotations

from src.data.providers.underdog_api import get_over_under_lines, raw_lines_to_props
from src.ingest.identity import resolve_player
from src.ingest.lines import record_prop_line
from src.ingest.runs import record_run
from src.utils.normalize import normalize_stat_type

SOURCE = "underdog"


async def ingest_props(db) -> tuple[int, int]:
    """Returns (rows_written, parked_count)."""
    payload = await get_over_under_lines()
    rows = [row for row in raw_lines_to_props(payload) if row["sport"] == "nfl"]

    written = 0
    parked = 0

    async with record_run(db, SOURCE) as run:
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
            )
            if player is None:
                # Unknown or ambiguous. Parked, never name-matched: two
                # active players are named Josh Allen and a wrong match
                # poisons the training set silently.
                parked += 1
                continue

            if await record_prop_line(
                db,
                player_id=player.id,
                game_id=None,
                stat_type=normalize_stat_type(row["raw_stat_type"]),
                line=row["line"],
                over_price_american=row["over_price_american"],
                under_price_american=row["under_price_american"],
                source=SOURCE,
            ):
                written += 1

        run.rows_written = written
        run.detail = f"{parked} appearances parked as unresolvable"
        await db.commit()
        return written, parked
