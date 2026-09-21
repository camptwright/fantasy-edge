"""Daily private-use market observations, exposed only for selected trade players."""
import hashlib
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
import httpx
from sqlalchemy import select,text
from config.settings import get_settings
from src.models.sleeper import SleeperLeague,SleeperRoster
from src.services.roster_stat_model import finite
from src.services.roster_stat_prospective import publish

SOURCE='https://api.fantasycalc.com/values/current'


def cohort(league,num_teams):
    if num_teams not in (8,10,12,14):return None
    ppr=league.scoring_settings.get('rec',0)
    if ppr not in (0,.5,1) or league.scoring_settings.get('bonus_rec_te',0):return None
    if league.platform=='sleeper':
        mode=league.settings.get('type')
        if mode not in (0,2):return None
        dynasty=mode==2
    elif league.platform=='espn':
        if league.settings.get('draftSettings',{}).get('keeperCount')!=0:return None
        dynasty=False
    else:return None
    qbs=league.roster_positions.count('QB')+league.roster_positions.count('SUPER_FLEX')
    if qbs not in (1,2):return None
    return {'isDynasty':str(dynasty).lower(),'numQbs':str(qbs),'numTeams':num_teams,'ppr':ppr,'tep':'none'}


def key(params):return hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()[:24]
def root():return Path(get_settings().raw_archive_dir)/'fantasy-market'


def normalize(rows):
    if not isinstance(rows,list) or not rows or len(rows)>10000:raise ValueError('invalid market payload')
    result=[];seen=set()
    for row in rows:
        p=row.get('player',{});pid=p.get('id');value=row.get('value')
        if not pid or pid in seen or not finite(value) or value<0:raise ValueError('invalid market row')
        seen.add(pid)
        result.append({'provider_player_id':str(pid),'position':p.get('position'),
            'sleeper_id':str(p['sleeperId']) if p.get('sleeperId') else None,
            'espn_id':str(p['espnId']) if p.get('espnId') else None,'value':value})
    return result


async def collect(db):
    reports=[]
    for league in (await db.scalars(select(SleeperLeague).where(SleeperLeague.sport=='nfl'))).all():
        rosters=(await db.scalars(select(SleeperRoster).where(SleeperRoster.league_id==league.league_id))).all()
        params=cohort(league,len(rosters))
        if params is None:
            reports.append({'league_id':league.league_id,'status':'unsupported_or_unverified_format'});continue
        k=key(params);directory=root()/k
        await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'fantasy-market:'+k})
        now=datetime.now(timezone.utc)
        attempts=sorted((directory/'attempts').glob('*.json'),reverse=True)
        if attempts and now-datetime.fromisoformat(json.loads(attempts[0].read_text())['at'])<timedelta(days=1):
            reports.append({'league_id':league.league_id,'status':'daily_cache'});await db.commit();continue
        stamp=now.strftime('%Y%m%dT%H%M%S.%f')
        publish(directory/'attempts'/(stamp+'.json'),{'at':now.isoformat(),'format':params})
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response=await client.get(SOURCE,params=params);response.raise_for_status()
            rows=normalize(response.json())
            publish(directory/'snapshots'/(stamp+'.json'),{'source':SOURCE,'captured_at':now.isoformat(),
                'provider_updated_at':None,'format':params,'rows':rows,
                'sha256':hashlib.sha256(response.content).hexdigest(),
                'attribution':'FantasyCalc','terms':'https://fantasycalc.com/terms-of-usage'})
            reports.append({'league_id':league.league_id,'status':'captured','rows':len(rows)})
        except (httpx.HTTPError,ValueError,TypeError,KeyError,AttributeError):
            reports.append({'league_id':league.league_id,'status':'provider_unavailable_or_invalid'})
        await db.commit()
    return reports


def selected(params,platform,ids,*,now=None,archive_root=None):
    base={'status':'unavailable','attribution':'FantasyCalc','url':'https://fantasycalc.com',
          'format':params,'players':[],
          'note':'Observed market-value index, not dollars or fantasy points. Custom scoring is not fully represented; no endorsement or trade fairness claim.'}
    if len(ids)>12 or len(set(ids))!=len(ids):return {**base,'status':'invalid_selection'}
    if params is None:return {**base,'status':'unsupported_or_unverified_format'}
    directory=Path(archive_root or root())/key(params)/'snapshots'
    paths=sorted(directory.glob('*.json'),reverse=True)
    if not paths:return base
    try:
        row=json.loads(paths[0].read_text());at=datetime.fromisoformat(row['captured_at'])
        age=((now or datetime.now(timezone.utc))-at).total_seconds()
        if not 0<=age<=172800:return {**base,'status':'stale','captured_at':row['captured_at']}
        if row['format']!=params:return {**base,'status':'format_mismatch'}
        field={'sleeper':'sleeper_id','espn':'espn_id'}.get(platform)
        matches=[]
        for pid in ids:
            found=[r for r in row['rows'] if field and r.get(field)==pid]
            matches.append({'player_id':pid,'value':found[0]['value'] if len(found)==1 else None,
                            'identity_status':'exact' if len(found)==1 else 'missing_or_ambiguous'})
        return {**base,'status':'observed','players':matches,'captured_at':row['captured_at'],
                'provider_updated_at':row.get('provider_updated_at'),'source_sha256':row['sha256']}
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return {**base,'status':'invalid_archive'}
