"""Import published nflverse GSIS-to-ESPN identity links; never name-match."""
import asyncio
import csv
import io
from collections import defaultdict
import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from src.db.client import get_worker_db
from src.models.identity import Player, PlayerExternalId

URL = 'https://github.com/nflverse/nflverse-data/releases/download/players/players.csv'


async def sync():
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        response = await client.get(URL)
        response.raise_for_status()
    pairs = defaultdict(set)
    reverse = defaultdict(set)
    for row in csv.DictReader(io.StringIO(response.text)):
        gsis, espn = row.get('gsis_id'), row.get('espn_id', '')
        if gsis and espn.isdigit():
            pairs[gsis].add(espn)
            reverse[espn].add(gsis)
    written = 0
    async with get_worker_db() as db:
        players = (await db.scalars(select(Player).where(Player.sport == 'nfl', Player.gsis_id.isnot(None)))).all()
        for player in players:
            values = pairs.get(player.gsis_id, set())
            if len(values) != 1:
                continue
            espn = next(iter(values))
            if len(reverse[espn]) != 1:
                continue
            existing = (await db.scalars(select(PlayerExternalId).where(PlayerExternalId.player_id == player.id,
                PlayerExternalId.source == 'espn_nfl'))).all()
            if existing:
                continue
            result = await db.scalar(insert(PlayerExternalId).values(player_id=player.id, source='espn_nfl', external_id=espn)
                .on_conflict_do_nothing(index_elements=['source', 'external_id']).returning(PlayerExternalId.id))
            written += result is not None
        await db.commit()
    return {'identity_links_added': written}


if __name__ == '__main__':
    print(asyncio.run(sync()))
