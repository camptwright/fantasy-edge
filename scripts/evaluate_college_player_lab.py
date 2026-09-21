"""Refresh official-provider conference snapshot, then run Power Four replay."""
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
from config.settings import get_settings
import httpx
from src.db.client import get_worker_db
from src.services.college_player_lab import membership, run

async def evaluate(full=False):
    now = datetime.now(timezone.utc)
    cached = sorted((Path(get_settings().raw_archive_dir)/'college-player-lab'/'sources').glob('*.json'))
    if cached:
        snapshot = json.loads(cached[-1].read_text())
        age = now-datetime.fromisoformat(snapshot['fetched_at'])
        if snapshot['season']==now.year and timedelta(0)<=age<timedelta(hours=6):
            async with get_worker_db() as db:
                return await run(db,snapshot,full=full)
    url = 'https://site.api.espn.com/apis/v2/sports/football/college-football/standings'
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url,params={'season':now.year})
        response.raise_for_status()
    snapshot = {'season':now.year,'fetched_at':now.isoformat(),'source':url,'teams':membership(response.json())}
    snapshot['rosters'] = {}
    semaphore = asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=30) as client:
        async def roster(team_id):
            async with semaphore:
                response = await client.get(f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{team_id}/roster')
                response.raise_for_status()
                payload = response.json()
                if str(payload.get('team',{}).get('id')) != team_id:
                    raise ValueError('Roster team mismatch')
                for group in payload.get('athletes',[]):
                    for athlete in group.get('items',[]):
                        pid = str(athlete.get('id',''))
                        if not pid: continue
                        value = {'team_id':team_id,'position':athlete.get('position',{}).get('abbreviation')}
                        if pid in snapshot['rosters'] and snapshot['rosters'][pid] != value:
                            raise ValueError('Conflicting roster membership')
                        snapshot['rosters'][pid] = value
        await asyncio.gather(*(roster(team) for team in snapshot['teams']))
    async with get_worker_db() as db:
        return await run(db,snapshot,full=full)

if __name__=='__main__':
    import json
    print(json.dumps(asyncio.run(evaluate())))
