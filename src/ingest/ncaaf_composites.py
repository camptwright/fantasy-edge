"""Exact observed-component sums; absence never means zero or participation."""
import math
from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from src.models.facts import Game, PlayerGameStat
from src.services.result_eligibility import no_pending_correction

COMPOSITES = {'pass_rush_yards': ('passing_yards', 'rushing_yards'),
              'rush_rec_yards': ('rushing_yards', 'receiving_yards'),
              'rush_rec_tds': ('rushing_touchdowns', 'receiving_touchdowns')}


def composite_values(values):
    return {name: sum(values[k] for k in keys) for name, keys in COMPOSITES.items()
            if all(k in values and math.isfinite(values[k]) for k in keys)}


async def derive_composites(db, game_ids=None, *, sport='ncaaf'):
    if sport not in ('nfl', 'ncaaf'):
        raise ValueError('Football composite sport required')
    components = {k for keys in COMPOSITES.values() for k in keys}
    stmt = select(PlayerGameStat).join(Game, Game.id == PlayerGameStat.game_id).where(
        Game.sport == sport, Game.status == 'final', no_pending_correction(),
        PlayerGameStat.stat_type.in_(components))
    if game_ids is not None:
        stmt = stmt.where(Game.id.in_(game_ids))
    grouped = defaultdict(dict)
    for row in (await db.scalars(stmt)).all():
        grouped[(row.player_id, row.game_id)][row.stat_type] = row.value
    rows = [{'player_id': player, 'game_id': game, 'stat_type': stat, 'value': value}
            for (player, game), values in grouped.items() for stat, value in composite_values(values).items()]
    written = 0
    for start in range(0, len(rows), 500):
        result = await db.execute(insert(PlayerGameStat).values(rows[start:start+500])
            .on_conflict_do_nothing(index_elements=['player_id', 'game_id', 'stat_type']).returning(PlayerGameStat.id))
        written += len(result.all())
    return written
