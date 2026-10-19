"""The owner's never-drop list per league (fantasy_never_drop).

Drop suggestions (waiver_guidance, fantasy_locks.waivers) skip these players;
they still count in the lineup. Read inline by fantasy_decision_models so this
module stays outside the versioned prediction code.
"""
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from src.models.sleeper import FantasyNeverDrop, SleeperLeague


class UnknownLeague(ValueError):
    pass


async def listing(db, league_id: str) -> list[dict]:
    rows = (await db.scalars(select(FantasyNeverDrop).where(FantasyNeverDrop.league_id == league_id)
                             .order_by(FantasyNeverDrop.added_at))).all()
    return [{"player_id": r.player_id, "added_at": r.added_at.isoformat()} for r in rows]


async def add(db, league_id: str, player_id: str) -> list[dict]:
    if await db.get(SleeperLeague, league_id) is None:
        raise UnknownLeague(league_id)
    await db.execute(insert(FantasyNeverDrop).values(league_id=league_id, player_id=player_id)
                     .on_conflict_do_nothing(index_elements=["league_id", "player_id"]))
    await db.commit()
    return await listing(db, league_id)


async def remove(db, league_id: str, player_id: str) -> list[dict]:
    await db.execute(delete(FantasyNeverDrop).where(FantasyNeverDrop.league_id == league_id,
                                                   FantasyNeverDrop.player_id == player_id))
    await db.commit()
    return await listing(db, league_id)
