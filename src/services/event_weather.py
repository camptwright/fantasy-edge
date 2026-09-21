"""Bounded event-specific source evidence, not home-team venue inference."""
import asyncio
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
from sqlalchemy import select, or_
from config.settings import get_settings
from src.models.facts import Game
from src.services.weather_evidence import fetch_forecast, features


def prioritize(games, root):
    """Fair bounded refresh: never-observed games, then oldest archive first."""
    def key(game):
        paths=sorted((root/'games'/str(game.id)).glob('*.json'))
        return (game.game_time is None, paths[-1].name if paths else '',
                game.game_time or datetime.max.replace(tzinfo=timezone.utc),str(game.id))
    return sorted(games,key=key)


def binding(payload, game):
    if not isinstance(payload,dict):return {'status':'malformed_event_payload'}
    if game.sport=='mlb':
        matches=[g for d in payload.get('dates',[]) for g in d.get('games',[]) if str(g.get('gamePk'))==game.mlb_game_pk]
        if len(matches)!=1: return {'status':'event_identity_mismatch'}
        event=matches[0];venue=event.get('venue',{})
        if event.get('gameDate') and getattr(game,'game_time',None):
            if datetime.fromisoformat(event['gameDate'].replace('Z','+00:00'))!=game.game_time:
                return {'status':'provider_kickoff_mismatch'}
        coordinates=venue.get('location',{}).get('defaultCoordinates',{})
        roof={'Open':'outdoor','Dome':'closed','Retractable':'retractable_unknown'}.get(venue.get('fieldInfo',{}).get('roofType'),'unknown')
    else:
        header=payload.get('header',{})
        if str(header.get('id'))!=game.espn_event_id: return {'status':'event_identity_mismatch'}
        event=header
        provider_time=next((c.get('date') for c in header.get('competitions',[]) if str(c.get('id'))==game.espn_event_id),None)
        if getattr(game,'game_time',None):
            if not provider_time:return {'status':'missing_provider_kickoff'}
            if datetime.fromisoformat(provider_time.replace('Z','+00:00'))!=game.game_time:
                return {'status':'provider_kickoff_mismatch'}
        venue=payload.get('gameInfo',{}).get('venue',{})
        coordinates={}  # ESPN event venue does not establish coordinates or roof state.
        roof='unknown'
    if not venue.get('id'): return {'status':'missing_event_venue'}
    lat,lon=coordinates.get('latitude'),coordinates.get('longitude')
    valid=all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (lat,lon))
    valid=valid and -90<=lat<=90 and -180<=lon<=180
    return {'status':'source_bound_coordinates' if valid else 'venue_bound_coordinates_missing',
            'venue_id':str(venue['id']),'name':venue.get('name') or venue.get('fullName'),
            'latitude':lat if valid else None,'longitude':lon if valid else None,'roof':roof,
            'provider_event_id':str(event.get('gamePk') or event.get('id')),
            'verification':'exact_provider_event_to_venue_not_independent_survey'}


async def collect(db):
    from src.services.roster_stat_prospective import publish
    now=datetime.now(timezone.utc);root=Path(get_settings().raw_archive_dir)/'event-weather'
    games=[];truncated={};coverage={}
    for sport in ('nfl','ncaaf','mlb'):
        rows=list((await db.scalars(select(Game).where(Game.sport==sport,Game.status=='scheduled',
            or_(Game.game_time.is_(None),(Game.game_time>now)&(Game.game_time<=now+timedelta(hours=72))))
            .order_by(Game.game_time.asc().nullslast(),Game.id).limit(501))).all())
        selected=prioritize(rows[:500],root)[:8]
        games+=selected;truncated[sport]=len(rows)>8
        coverage[sport]={'eligible_scanned':min(len(rows),500),'scan_truncated':len(rows)>500,
                         'selected':len(selected),'unknown_kickoffs':sum(g.game_time is None for g in rows[:500])}
    semaphore=asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=12) as client:
        from src.services.football_venue_coordinates import dataset,match,SOURCE
        try:coordinate_rows,coordinate_hash=await dataset(client)
        except (httpx.HTTPError,ValueError):coordinate_rows,coordinate_hash=[],None
        async def one(game):
            async with semaphore:
                stamp=datetime.now(timezone.utc)
                record={'game_id':str(game.id),'sport':game.sport,'kickoff':game.game_time.isoformat() if game.game_time else None,
                        'captured_at':stamp.isoformat(),'serving_enabled':False}
                try:
                    if not game.game_time: record['status']='unknown_kickoff'
                    else:
                        if game.sport=='mlb' and game.mlb_game_pk:
                            url='https://statsapi.mlb.com/api/v1/schedule';params={'gamePk':game.mlb_game_pk,'hydrate':'venue(location,fieldInfo)'}
                        elif game.sport in ('nfl','ncaaf') and game.espn_event_id:
                            league='nfl' if game.sport=='nfl' else 'college-football'
                            url=f'https://site.api.espn.com/apis/site/v2/sports/football/{league}/summary';params={'event':game.espn_event_id}
                        else: raise ValueError('missing_provider_event_id')
                        response=await client.get(url,params=params);response.raise_for_status();source=response.json()
                        venue=binding(source,game)
                        if venue['status']=='venue_bound_coordinates_missing':
                            evidence=match(source.get('gameInfo',{}).get('venue',{}),coordinate_rows,game.season)
                            if evidence:
                                venue.update(evidence,status='secondary_coordinates_roof_unverified',coordinate_source_sha256=coordinate_hash)
                        record.update(venue=venue,event_source=url,event_source_params=params,event_payload=source,
                            event_sha256=hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest(),
                            event_hash_encoding='canonical_json_sort_keys',status=venue['status'])
                        if venue['status'] in ('source_bound_coordinates','secondary_coordinates_roof_unverified'):
                            if venue['roof']=='closed': record['status']='indoor_weather_not_applied'
                            else:
                                forecast=await fetch_forecast(venue['latitude'],venue['longitude'])
                                record['forecast']=forecast
                                record['status']='forecast_archived'
                except (httpx.HTTPError,ValueError,KeyError,TypeError,AttributeError):
                    record['status']='source_unavailable_or_invalid'
                record['captured_at']=datetime.now(timezone.utc).isoformat()
                record['id']=hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()
                filename=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%f')+'-'+record['id'][:12]+'.json'
                publish(root/'games'/str(game.id)/filename,record)
                return {k:record.get(k) for k in ('game_id','sport','status','venue','captured_at')}
        rows=await asyncio.gather(*(one(g) for g in games))
    report={'generated_at':datetime.now(timezone.utc).isoformat(),'rows':rows,'truncated':truncated,
        'coverage':coverage,'selection_policy':'unobserved_then_oldest_known_kickoff_first',
        'scope':'next_72h_max_8_games_per_sport','serving_enabled':False}
    publish(root/'reports'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%f')+'.json'),report)
    return report


def context(game, as_of, root=None):
    root=Path(root or get_settings().raw_archive_dir)/'event-weather'/'games'/str(game.id)
    base={'status':'no_prior_weather_archive','serving_enabled':False}
    for path in sorted(root.glob('*.json'),reverse=True)[:48]:
        try:
            row=json.loads(path.read_text());captured=datetime.fromisoformat(row['captured_at'])
            if captured>as_of:continue
            if not game.game_time or row['kickoff']!=game.game_time.isoformat():
                return {**base,'status':'kickoff_changed_or_unknown'}
            if as_of-captured>timedelta(hours=6): return {**base,'status':'stale_weather_archive'}
            result={**base,'status':row['status'],'archive_id':row['id'],'venue':row.get('venue')}
            if row.get('forecast'):
                forecast=row['forecast'];result['weather']=features(forecast['payload'],
                    captured_at=datetime.fromisoformat(forecast['captured_at']),kickoff=game.game_time,
                    as_of=as_of,roof=row['venue']['roof'])
            return result
        except (OSError,ValueError,KeyError,TypeError):continue
    return base


def latest():
    root=Path(get_settings().raw_archive_dir)/'event-weather'/'reports'
    paths=sorted(root.glob('*.json'),reverse=True)
    if not paths:return {'status':'not_captured','rows':[],'serving_enabled':False}
    try:
        report=json.loads(paths[0].read_text())
        generated=datetime.fromisoformat(report['generated_at'])
        age=(datetime.now(timezone.utc)-generated).total_seconds()
        from src.services.settlement_evidence import latest as rule_evidence
        return {**report,'settlement_evidence':rule_evidence(),'report_age_seconds':max(0,round(age)),
                'report_freshness':'current' if 0<=age<=7200 else 'stale_or_invalid_timestamp'}
    except (OSError,ValueError,TypeError,KeyError):return {'status':'unreadable_report','rows':[],'serving_enabled':False}
