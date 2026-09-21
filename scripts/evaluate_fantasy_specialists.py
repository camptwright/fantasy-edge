"""Evaluate archived kicker evidence without downloading data or promoting models."""
import asyncio
import hashlib
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from sqlalchemy import select
from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.sleeper import SleeperLeague
from src.ingest.fantasy_scoring import parse
from src.services.fantasy_decision_models import player_scoring
from src.services.fantasy_specialists import holdout
from src.services.roster_stat_prospective import publish


async def execute():
    root=Path(get_settings().raw_archive_dir)
    archives={}
    for path in sorted((root/'fantasy-scoring-source').glob('*.json')):
        row=json.loads(path.read_text());archives[int(row['season'])]=(path,row)
    now=datetime.now(timezone.utc);season=(now.year if now.month>=8 else now.year-1)-1
    rows=[];sources=[]
    for year in (season-1,season):
        if year not in archives:continue
        path,archive=archives[year]
        sources.append({'season':year,'sha256':archive['sha256'],'archive':path.name})
        for r in archive['rows']:
            if r.get('position')!='K' or r.get('season_type')!='REG':continue
            week=int(r['week'])
            rows.append({'player_id':r['player_id'],'game_id':r['game_id'],'season':year,'week':week,
                # Ordering key only, not an asserted game kickoff or capture timestamp.
                'time':datetime(year,1,1,tzinfo=timezone.utc)+timedelta(weeks=week),'values':parse(r)})
    reports=[]
    async with get_worker_db() as db:
        for league in (await db.scalars(select(SleeperLeague).where(SleeperLeague.sport=='nfl'))).all():
            scoring,gaps=player_scoring(league,'K')
            report=holdout(rows,scoring,season)
            reports.append({**report,'league_id':league.league_id,'rule_gaps':gaps,
                            'scoring_sha256':hashlib.sha256(json.dumps(scoring,sort_keys=True).encode()).hexdigest()})
    result={'generated_at':now.isoformat(),'status':'retrospective_research','sources':sources,
            'kicker':reports,'rookie':{'status':'requires_verified_rookie_cohorts_and_holdout'},
            'dst':{'status':'requires_team_defense_scoring_reconciliation'},'serving_promoted':False}
    publish(root/'fantasy-specialists'/'reports'/(now.strftime('%Y%m%dT%H%M%S.%f')+'.json'),result)
    return result


if __name__=='__main__':print(json.dumps(asyncio.run(execute())))
