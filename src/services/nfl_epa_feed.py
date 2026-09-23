"""Free weekly NFL feed and timestamped EPA features; no implicit model weights."""
import csv
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path
import httpx
from config.settings import get_settings
from src.ingest.players import ingest_player_stats,_game_for
from src.models.base import utcnow
from src.services.roster_stat_model import finite
from src.services.roster_stat_prospective import publish
from src.services.nfl_predictor_lab import team_key


def number(value):
    try:value=float(value)
    except (TypeError,ValueError):return None
    return value if finite(value) else None


async def refresh(db,season):
    now=utcnow();features=[];stats_written=0;sources=[]
    async with httpx.AsyncClient(timeout=90,follow_redirects=True) as client:
        for kind,year in [('player',season),('team',season-1),('team',season)]:
            url=f'https://github.com/nflverse/nflverse-data/releases/download/stats_{kind}/stats_{kind}_week_{year}.csv'
            response=await client.get(url);response.raise_for_status()
            rows=list(csv.DictReader(io.StringIO(response.text)))
            sources.append({'url':url,'sha256':hashlib.sha256(response.content).hexdigest(),'rows':len(rows)})
            accepted=[]
            for row in rows:
                if str(row.get('season'))!=str(year) or row.get('season_type') not in ('REG','POST'):continue
                try:row['season']=int(row['season']);row['week']=int(row['week'])
                except (KeyError,ValueError,TypeError):continue
                game=await _game_for(db,row)
                if not game or game.status!='final' or not game.game_time or game.game_time>=now:continue
                if row.get('game_id') and game.nflverse_game_id and row['game_id']!=game.nflverse_game_id:continue
                if kind=='player':
                    accepted.append(row);continue
                passing,rushing=number(row.get('passing_epa')),number(row.get('rushing_epa'))
                if passing is None or rushing is None:continue
                features.append({'game_id':str(game.id),'season':year,'week':row['week'],
                    'team':team_key(row.get('team')),'opponent':team_key(row.get('opponent_team')),
                    'kickoff':game.game_time.isoformat(),'passing_epa':passing,'rushing_epa':rushing,
                    'offensive_epa':passing+rushing,'observed_at':now.isoformat()})
            if kind=='player':stats_written=await ingest_player_stats(db,[season],records=accepted)
    root=Path(get_settings().raw_archive_dir)/'nfl-epa'
    payload={'observed_at':now.isoformat(),'sources':sources,'rows':features,
        'scope':'corrected_weekly_EPA_observed_now_not_historical_asof_evidence'}
    publish(root/f'{now.strftime("%Y%m%dT%H%M%S%f")}.json',payload)
    await db.commit()
    return {'player_stats_inserted':stats_written,'epa_team_games':len(features),'sources':sources}


def features_for(rows,team,as_of):
    selected=[r for r in rows if r['team']==team and datetime.fromisoformat(r['observed_at'])<=as_of
        and datetime.fromisoformat(r['kickoff']).date()<as_of.date()]
    unique={r['game_id']:r for r in selected}
    recent=sorted(unique.values(),key=lambda r:r['kickoff'])[-8:]
    if len(recent)<4:return {'status':'insufficient_history','games':len(recent)}
    return {'status':'research_features','games':len(recent),
        **{key:sum(r[key] for r in recent)/len(recent) for key in ('passing_epa','rushing_epa','offensive_epa')},
        'game_ids':[r['game_id'] for r in recent],'scope':'last8_team_game_EPA_not_per_play'}


def latest_features(home,away,now):
    paths=sorted((Path(get_settings().raw_archive_dir)/'nfl-epa').glob('*.json'))
    if not paths:return {'status':'missing_epa_archive'}
    data=json.loads(paths[-1].read_text());observed=datetime.fromisoformat(data['observed_at'])
    if not 0<=(now-observed).total_seconds()<=48*3600:return {'status':'stale_epa_archive'}
    return {'observed_at':data['observed_at'],'home':features_for(data['rows'],home,now),
        'away':features_for(data['rows'],away,now),'used_in_serving':False,
        'note':'Frozen candidate features; EPA coefficients still require separate training and holdout evaluation.'}
