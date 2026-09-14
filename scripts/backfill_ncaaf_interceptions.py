"""Add canonical interception facts without deleting legacy observations."""
import asyncio
from sqlalchemy import text
from src.db.client import get_worker_db


async def backfill(db):
    result = await db.execute(text("""
        INSERT INTO player_game_stats (id, player_id, game_id, stat_type, value)
        SELECT gen_random_uuid(), s.player_id, s.game_id, 'passing_interceptions', s.value
        FROM player_game_stats s JOIN games g ON g.id=s.game_id
        WHERE g.sport='ncaaf' AND s.stat_type='ints_thrown'
        ON CONFLICT (player_id, game_id, stat_type) DO NOTHING
        RETURNING id
    """))
    count = len(result.all())
    await db.commit()
    return count


async def main():
    async with get_worker_db() as db:
        print({'canonical_rows_added': await backfill(db)})


if __name__ == '__main__':
    asyncio.run(main())
