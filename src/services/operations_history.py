"""Bounded durable operations observations; never logs tokens or raw URLs."""
from datetime import datetime,timezone
import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from config.settings import get_settings
from src.models.governance import DerivedCheckpoint
from src.services.forecast_evidence import digest,capture_status

NAME='operations-history'


def alerts(performance,capture,previous=None):
    rows=[]
    if performance.get('status')=='unreachable':rows.append('api_unreachable')
    if capture.get('stale',True):rows.append('production_capture_overdue_or_unknown')
    if previous and previous.get('process_id') and performance.get('process_id') and previous['process_id']!=performance['process_id']:
        rows.append('api_process_changed_restart_or_deployment')
    for route,stats in performance.get('routes',{}).items():
        if stats.get('p95_ms',0)>2000:rows.append('slow_route:'+route)
        if stats.get('server_errors',0):rows.append('server_errors:'+route)
    return rows


async def collect(db):
    settings=get_settings()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response=await client.get('http://api:8000/operations/performance',
                headers={'Authorization':'Bearer '+settings.fantasy_api_token})
            response.raise_for_status()
            performance=response.json()
    except (httpx.HTTPError,ValueError):
        performance={'status':'unreachable'}
    capture=await capture_status(db)
    await db.execute(text('SELECT pg_advisory_xact_lock(79431802)'))
    old=await db.get(DerivedCheckpoint,NAME)
    prior=old.payload if old and digest(old.payload)==old.digest else {}
    warnings=alerts(performance,capture,prior.get('latest',{}).get('performance'))
    stamp=datetime.now(timezone.utc).isoformat()
    latest={'at':stamp,'performance':performance,'capture':capture,'alerts':warnings}
    history=prior.get('history',[])[-287:]+[{'at':stamp,'process_id':performance.get('process_id'),
        'api_status':performance.get('status','reachable'),'peak_rss_bytes':performance.get('peak_rss_bytes'),
        'alerts':warnings}]
    payload={'latest':latest,'history':history}
    values={'name':NAME,'digest':digest(payload),'payload':payload,'updated_at':datetime.now(timezone.utc)}
    await db.execute(insert(DerivedCheckpoint).values(**values).on_conflict_do_update(
        index_elements=['name'],set_={k:v for k,v in values.items() if k!='name'}))
    await db.commit()
    return {'at':stamp,'alerts':warnings,'observations':len(history)}


async def status(db):
    row=await db.get(DerivedCheckpoint,NAME)
    if row is None or digest(row.payload)!=row.digest:
        return {'status':'awaiting_monitor','alerts':['monitor_history_unavailable'],'history':[]}
    p=row.payload
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(p['latest']['at'])).total_seconds()
    stale=not 0<=age<=660
    return {**p,'status':'stale' if stale else 'current','age_seconds':round(age),
        'alerts':p['latest']['alerts']+(['monitor_heartbeat_overdue'] if stale else []),
        'scope':'Latest 288 five-minute observations; API latency is its rolling last 200 requests per route, not a fixed time window. Process changes include planned deployments. Alerts are in-app, not external notifications.'}
