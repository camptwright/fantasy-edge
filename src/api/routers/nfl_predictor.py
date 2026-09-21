"""Read-only experimental page contract. No serving-model side effects."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
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
async def missing_results(db: AsyncSession = Depends(get_db)):
    from src.services.missing_result_queue import queue
    return await queue(db)
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
async def college_players():
    from src.services.college_player_lab import latest
    from src.services.college_prospective import latest as prospective
    return {**await run_in_threadpool(latest),'prospective':await run_in_threadpool(prospective)}


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
    return {'status':'experimental','generated_at':now.isoformat(),'version':artifact['version'],
            'recipe':artifact['recipe'],'training_games':artifact['training_games'],
            'history_games':artifact['history_games'],'history_through':artifact['history_through'],
            'new_results_applied':len(results),'evaluation':artifact['evaluation'],'games':predictions}
