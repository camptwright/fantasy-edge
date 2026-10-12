"""Read-only experimental page contract. No serving-model side effects."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from src.db.client import get_db
from src.models.facts import Game
from src.models.identity import Team
from src.services.nfl_predictor_lab import predict_games, team_key

router = APIRouter()


@router.get('/experiments/weather-context')
async def weather_context_status():
    from src.services.event_weather import latest
    return await run_in_threadpool(latest)


@router.get('/experiments/missing-results')
async def missing_results(db: AsyncSession = Depends(get_db),
                          limit: int = Query(default=200,ge=1,le=500),
                          offset: int = Query(default=0,ge=0)):
    from src.services.missing_result_queue import queue
    return await queue(db,limit=limit,offset=offset)
ARTIFACT = Path(__file__).resolve().parents[3]/'config'/'nfl_predictor_lab.json'


@router.get('/experiments/nfl-players')
async def roster_stat_predictor(league_id: str | None = None, db: AsyncSession = Depends(get_db)):
    from src.services.roster_stat_lab import build
    from src.services.roster_stat_prospective import latest
    return {**await build(db, league_id), 'prospective': await run_in_threadpool(latest)}


@router.get('/experiments/football-props')
async def football_prop_research():
    from src.services.period_research_status import status
    return await run_in_threadpool(status)


@router.get('/experiments/college-players')
async def college_players(compact: bool = False, team: str | None = Query(default=None,max_length=200),
                          offset: int = Query(default=0,ge=0), limit: int = Query(default=50,ge=1,le=100)):
    from src.services.college_player_lab import latest
    from src.services.college_prospective import latest as prospective
    from src.services.college_lab_view import compact as display
    def read():
        report=latest()
        return display(report,team=team,offset=offset,limit=limit) if compact else report
    return {**await run_in_threadpool(read),'prospective':await run_in_threadpool(prospective)}


@router.get('/experiments/nfl-predictor/governance')
async def nfl_governance(db: AsyncSession = Depends(get_db)):
    """Expose only the current artifact's durable review, never a stale winner."""
    from src.models.governance import ModelArtifact, ModelReviewEvidence
    from src.services.nfl_lab_registry import artifact_version
    from src.services.model_deployment import selection
    if not ARTIFACT.exists():
        return {'status':'not_trained','serving_promoted':False}
    version=artifact_version(json.loads(ARTIFACT.read_text()))
    artifact=await db.scalar(select(ModelArtifact).where(ModelArtifact.version==version))
    evidence=await db.scalar(select(ModelReviewEvidence).where(ModelReviewEvidence.artifact_version==version)
        .order_by(ModelReviewEvidence.created_at.desc(),ModelReviewEvidence.id.desc()).limit(1))
    selected=await selection(db)
    return {'version':version,'status':'review_available' if evidence else 'awaiting_durable_review',
        'artifact_registered':artifact is not None,
        'artifact_payload_persisted':artifact is not None and artifact.artifact_payload is not None,
        'review':evidence.report if evidence else None,'serving_promoted':selected['status']=='approved',
        'serving_selection':selected,
        'automatic_deployment':False}


@router.get('/experiments/nfl-predictor')
async def nfl_predictor(db: AsyncSession = Depends(get_db)):
    if not ARTIFACT.exists():
        return {'status':'not_trained','games':[]}
    artifact = json.loads(ARTIFACT.read_text())
    now = datetime.now(timezone.utc)
    teams = {t.id:t for t in (await db.scalars(select(Team).where(Team.sport=='nfl'))).all()}
    games = (await db.scalars(select(Game).where(Game.sport=='nfl',
        or_(Game.game_type.is_(None),Game.game_type!='PRE'),
        Game.season > artifact['last_season'],
        or_(Game.game_time.is_(None), Game.game_time <= now+timedelta(days=14)))
        .order_by(Game.game_time.asc().nullslast()))).all()
    scheduled, results = [], []
    for g in games:
        if g.home_team_id not in teams or g.away_team_id not in teams:
            continue
        h,a = teams[g.home_team_id], teams[g.away_team_id]
        # nflverse dates are Eastern-local, not UTC (night games cross UTC days).
        from zoneinfo import ZoneInfo
        day = g.game_time.astimezone(ZoneInfo('America/New_York')).date().isoformat() if g.game_time else None
        home, away = team_key(h.nflverse_abbr),team_key(a.nflverse_abbr)
        venue = artifact['venues'].get(f'{g.season}:{home}:{away}:{day}')
        row = {'id':str(g.id),'season':g.season,'week':g.week,'date':day,
               'game_time':g.game_time.isoformat() if g.game_time else None,
               'home':home,'away':away,'home_name':h.name,'away_name':a.name,
               'neutral':bool(venue),'venue_verified':venue is not None}
        if g.status=='final' and day and day>artifact['history_through'] and g.game_time < now and g.home_score is not None and g.away_score is not None:
            # Same-day results are held until tomorrow, mirroring the training policy.
            if day < now.astimezone(ZoneInfo('America/New_York')).date().isoformat():
                results.append({**row,'home_score':g.home_score,'away_score':g.away_score})
        elif g.status=='scheduled' and (g.game_time is None or g.game_time>now):
            scheduled.append(row)
    predictions = await run_in_threadpool(predict_games,artifact,scheduled,results)
    from src.services.nfl_lab_registry import market_reference
    from src.services.nfl_epa_feed import latest_features
    game_by_id={str(g.id):g for g in games}
    for row in predictions:
        if row.get('home_probability') is None:continue
        market=await market_reference(db,game_by_id[row['id']],now)
        row['market_reference']=market
        row['market_blend_candidate_home_probability']=(.75*row['home_probability']+.25*market['probability']) if market else None
        row['market_blend_status']='research_only_unvalidated' if market else 'missing_fresh_sharp_market'
        row['epa_features']=await run_in_threadpool(latest_features,row['home'],row['away'],now)
        row['serving_promoted']=False
    return {'status':'experimental','generated_at':now.isoformat(),'version':artifact['version'],
            'recipe':artifact['recipe'],'training_games':artifact['training_games'],
            'history_games':artifact['history_games'],'history_through':artifact['history_through'],
            'new_results_applied':len(results),'evaluation':artifact['evaluation'],'games':predictions}
