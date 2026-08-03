"""CONSTRAINT #7: props list endpoints must use
`DISTINCT ON (player_name, stat_type, source) ORDER BY captured_at DESC`
or the UI shows hundreds of duplicates - PropsAgent ingests a fresh row on
every poll cycle rather than updating one in place (same append-and-dedup-
at-query-time pattern as BetSignal), so without DISTINCT ON, every historical
capture of the same line would render as a separate row.

CONSTRAINT #2 applies here too: `game_id` on a prop line is nullable
(Underdog gives no `teams` array to resolve it against - see CLAUDE.md #17),
so any join to `games` for context must be a LEFT JOIN, not an inner join
that would silently drop every prop whose game couldn't be resolved.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.serializers import row_to_dict
from src.data.cache.db_client import get_db
from src.models.orm import Game, PlayerPropLine

router = APIRouter(prefix="/props", tags=["props"])


async def _deduped_props(
    db: AsyncSession, *, sport: str | None, player_name: str | None, stat_type: str | None
) -> list[PlayerPropLine]:
    conditions = []
    if sport:
        conditions.append(PlayerPropLine.sport == sport)
    if player_name:
        conditions.append(PlayerPropLine.normalized_name.ilike(f"%{player_name.lower()}%"))
    if stat_type:
        conditions.append(PlayerPropLine.stat_type == stat_type)

    stmt = (
        select(PlayerPropLine)
        .distinct(
            PlayerPropLine.player_name, PlayerPropLine.stat_type, PlayerPropLine.source
        )
        .order_by(
            PlayerPropLine.player_name,
            PlayerPropLine.stat_type,
            PlayerPropLine.source,
            PlayerPropLine.captured_at.desc(),
        )
    )
    if conditions:
        stmt = stmt.where(*conditions)

    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("")
async def list_props(
    sport: str | None = None,
    player_name: str | None = None,
    stat_type: str | None = None,
    limit: int = Query(default=200, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = await _deduped_props(db, sport=sport, player_name=player_name, stat_type=stat_type)
    return [row_to_dict(r) for r in rows[:limit]]


@router.get("/best")
async def best_props(
    sport: str | None = None, limit: int = Query(default=50, le=200), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Ranks (player, stat) pairs by cross-source line spread - the bigger
    the disagreement between sources on the same number, the more likely one
    of them is stale or mispriced.
    """
    rows = await _deduped_props(db, sport=sport, player_name=None, stat_type=None)

    by_player_stat: dict[tuple[str, str], list[PlayerPropLine]] = {}
    for r in rows:
        by_player_stat.setdefault((r.normalized_name, r.stat_type), []).append(r)

    game_ids = {r.game_id for group in by_player_stat.values() for r in group if r.game_id}
    games_by_id: dict[str, Game] = {}
    if game_ids:
        result = await db.execute(select(Game).where(Game.id.in_(game_ids)))
        games_by_id = {str(g.id): g for g in result.scalars().all()}

    results = []
    for (_norm_name, _stat), group in by_player_stat.items():
        if len(group) < 2:
            continue
        lines = [g.line for g in group]
        spread = max(lines) - min(lines)
        if spread <= 0:
            continue
        primary = max(group, key=lambda g: g.captured_at)
        row = row_to_dict(primary)
        row["cross_source_spread"] = spread
        row["sources"] = [
            {"source": g.source, "line": g.line, "captured_at": g.captured_at} for g in group
        ]
        game = games_by_id.get(str(primary.game_id)) if primary.game_id else None
        row["matchup"] = (
            f"{game.away_team_name} @ {game.home_team_name}" if game else None
        )
        row["game_time"] = game.game_time if game else None
        results.append(row)

    results.sort(key=lambda r: r["cross_source_spread"], reverse=True)
    return results[:limit]


@router.get("/compare")
async def compare_props(
    player_name: str, stat_type: str, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Every source's current line for one player+stat, side by side."""
    rows = await _deduped_props(db, sport=None, player_name=player_name, stat_type=stat_type)
    return [row_to_dict(r) for r in rows]
