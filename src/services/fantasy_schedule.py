"""Complete regular-season membership, separate from kickoff-time certainty."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import httpx
from sqlalchemy import select
from config.settings import get_settings
from src.models.facts import Game


def validate(events, season):
    ids=set(); teams=Counter(); weeks=defaultdict(set)
    for event in events:
        if event['season']['year']!=season or event['season']['type']!=2:
            raise ValueError('wrong season/type')
        eid=event['id']; week=event['week']['number']
        if eid in ids or week not in range(1,19): raise ValueError('duplicate game or invalid week')
        ids.add(eid)
        sides=event['competitions'][0]['competitors']
        if len(sides)!=2 or {s['homeAway'] for s in sides}!={'home','away'}:
            raise ValueError('invalid competitors')
        for side in sides:
            team=side['team']['id']
            if week in weeks[team]: raise ValueError('team appears twice in week')
            teams[team]+=1; weeks[team].add(week)
    if len(ids)!=272 or len(teams)!=32 or set(teams.values())!={17}:
        raise ValueError('incomplete 17-game regular season')
    return {'games':272,'teams':32,'weeks':18,'bye_weeks':{t:sorted(set(range(1,19))-w) for t,w in weeks.items()}}


async def sync(db, season):
    from src.ingest.espn import _upsert_event
    from src.ingest.runs import record_run
    from src.scheduler.calibration import archive
    events=[]
    async with httpx.AsyncClient(timeout=30) as client:
        for week in range(1,19):
            r=await client.get(get_settings().espn_base_urls['nfl']+'/scoreboard',
                params={'dates':str(season),'seasontype':2,'week':week,'limit':1000})
            r.raise_for_status()
            rows=r.json().get('events',[])
            if any(e.get('week',{}).get('number')!=week for e in rows): raise ValueError('week response mismatch')
            events.extend(rows)
    report=validate(events,season)
    archive('fantasy-season-schedule',{'season':season,'observed_at':datetime.now(timezone.utc).isoformat(),
        'validation':report,'events':events})
    async with record_run(db,'espn_nfl_full_schedule') as run:
        for event in events:
            if await _upsert_event(db,event,run,'nfl') is None: raise ValueError('unresolved event')
        await db.commit()
    return report


def coverage(games):
    rows=[g for g in games if g.game_type=='REG']
    counts=Counter(); weeks=defaultdict(set); valid=True
    for g in rows:
        if g.week not in range(1,19) or not g.home_team_id or not g.away_team_id: valid=False; continue
        for tid in (g.home_team_id,g.away_team_id):
            if g.week in weeks[tid]: valid=False
            counts[tid]+=1; weeks[tid].add(g.week)
    complete=valid and len(rows)==272 and len(counts)==32 and set(counts.values())=={17}
    return {'complete':complete,'games':len(rows),'teams':len(counts),
        'unknown_kickoffs':sum(g.game_time is None for g in rows),
        'bye_weeks':{str(t):sorted(set(range(1,19))-w) for t,w in weeks.items()} if complete else {}}
