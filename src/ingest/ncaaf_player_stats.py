"""NCAAF player-game stats from ESPN's per-game boxscore (the `summary`
endpoint's `boxscore.players[]`) - the same role src/ingest/players.py's
ingest_player_stats plays for NFL via nflverse, which has no NCAAF
equivalent (docs/nfl-modeling.md). Without this, every NCAAF prop stays
permanently unqualified (src/services/projections.py needs
MIN_GAMES_FOR_PROJECTION realized games per player/stat_type) even once
the player itself resolves (src/ingest/ncaaf_players.py).

One request per finished game (verified live 2026-09-05 against a real
2025 game) - a seeding/backfill script like scripts/ingest_history.py, not
a live poller; run it after enough of a season's games have gone final.

Player resolution reuses resolve_player() directly rather than a custom
lookup: src/ingest/ncaaf_players.py already created a PlayerExternalId row
keyed (source="espn_ncaaf", external_id=<ESPN athlete id>) for every
rostered player, so a boxscore's own athlete.id hits that crosswalk
directly - the same mechanism Underdog/PrizePicks props already rely on,
just fed from the same ESPN id space instead of a name match.

Only the primitive box-score counting stats worth a market are ingested
(mirrors NFL's own STAT_COLUMNS curation - "anything not listed is ignored
rather than stored blindly"), not composite markets real NCAAF props also
reference (rush_rec_yards, pass_rush_yards, total_tds, first_td_scorer) -
those would need to be derived by summing rows across categories, the same
gap NFL's own player_game_stats already has for its own composite props.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.ingest.identity import resolve_player
from src.ingest.runs import record_run
from src.models.facts import Game, PlayerGameStat

SOURCE = "espn_ncaaf"

# category name -> {ESPN boxscore key -> canonical stat_type}. Canonical
# names match what real NCAAF props already use verbatim (checked live
# 2026-09-05 against this app's own player_prop_lines: receiving_yards,
# receptions, rushing_yards, rushing_attempts, passing_touchdowns,
# passing_yards, longest_rush, longest_reception, ints_thrown), not run
# through src/utils/normalize.py's generic normalize_stat_type() - ESPN's
# camelCase keys don't tokenize through that regex-based normalizer, and
# "interceptions" alone is ambiguous across categories (thrown here, under
# "passing"; caught under an unrelated "interceptions" defensive category
# this module doesn't ingest at all) in a way a generic normalizer can't
# disambiguate without knowing the category.
_STAT_MAP: dict[str, dict[str, str]] = {
    "passing": {
        "passingYards": "passing_yards",
        "passingTouchdowns": "passing_touchdowns",
        "interceptions": "ints_thrown",
    },
    "rushing": {
        "rushingAttempts": "rushing_attempts",
        "rushingYards": "rushing_yards",
        "rushingTouchdowns": "rushing_touchdowns",
        "longRushing": "longest_rush",
    },
    "receiving": {
        "receptions": "receptions",
        "receivingYards": "receiving_yards",
        "receivingTouchdowns": "receiving_touchdowns",
        "longReception": "longest_reception",
    },
}
# The one compound field ESPN emits ("16/31") - split into the two
# canonical stat_types real props actually use separately.
_COMPOUND_KEY = "completions/passingAttempts"


def _number(value: Any) -> float | None:
    if value in (None, "", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def ingest_player_stats(db: AsyncSession, seasons: list[int]) -> int:
    games = (
        await db.execute(
            select(Game).where(
                Game.sport == "ncaaf", Game.season.in_(seasons), Game.status == "final"
            )
        )
    ).scalars().all()

    async with record_run(db, f"{SOURCE}:player_stats") as run:
        async with httpx.AsyncClient(timeout=20.0) as client:
            for game in games:
                if not game.espn_event_id:
                    continue
                response = await client.get(
                    f"{get_settings().espn_base_urls['ncaaf']}/summary",
                    params={"event": game.espn_event_id},
                )
                if response.status_code != 200:
                    run.detail = f"game {game.espn_event_id}: HTTP {response.status_code}"[:2000]
                    continue
                payload = response.json()
                boxscore = payload.get("boxscore") or {}
                for team_block in boxscore.get("players") or []:
                    for category in team_block.get("statistics") or []:
                        run.rows_written += await _ingest_category(db, game.id, category)
        await db.commit()
        return run.rows_written


async def _ingest_category(db: AsyncSession, game_id: Any, category: dict[str, Any]) -> int:
    category_name = category.get("name")
    stat_map = _STAT_MAP.get(category_name)
    keys = category.get("keys") or []
    written = 0

    for entry in category.get("athletes") or []:
        athlete = entry.get("athlete") or {}
        external_id = str(athlete.get("id") or "")
        full_name = athlete.get("displayName")
        if not external_id or not full_name:
            continue
        values = dict(zip(keys, entry.get("stats") or []))

        pairs: list[tuple[str, Any]] = []
        if category_name == "passing" and _COMPOUND_KEY in values:
            completions, _, attempts = str(values[_COMPOUND_KEY]).partition("/")
            pairs.append(("passing_completions", completions))
            pairs.append(("passing_attempts", attempts))
        if stat_map:
            for key, canonical in stat_map.items():
                if key in values:
                    pairs.append((canonical, values[key]))
        if not pairs:
            continue

        player = await resolve_player(
            db, source=SOURCE, external_id=external_id, full_name=full_name, sport="ncaaf"
        )
        if player is None:
            continue

        for stat_type, raw_value in pairs:
            number = _number(raw_value)
            if number is None:
                continue
            result = await db.execute(
                insert(PlayerGameStat)
                .values(player_id=player.id, game_id=game_id, stat_type=stat_type, value=number)
                .on_conflict_do_nothing(index_elements=["player_id", "game_id", "stat_type"])
            )
            if result.rowcount:
                written += 1
    return written
