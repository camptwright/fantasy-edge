"""Read-only DB evaluation of archived exact-league full-scoring K/DST outcomes."""
import asyncio
import json
from sqlalchemy import select
from src.db.client import get_worker_db
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot
from src.services.fantasy_specialist_totals import holdout


async def execute():
    reports=[]
    async with get_worker_db() as db:
        leagues=(await db.scalars(select(SleeperLeague).where(SleeperLeague.sport=='nfl'))).all()
        for league in leagues:
            snapshots=(await db.scalars(select(SleeperLeagueSnapshot).where(
                SleeperLeagueSnapshot.league_id==league.league_id))).all()
            metadata=sorted((s for s in snapshots if s.kind=='player_metadata'), key=lambda s:s.synced_at)
            catalog=metadata[-1].payload if metadata else {}
            contracts={}
            for snap in sorted(snapshots,key=lambda s:s.synced_at):
                p=snap.payload
                if snap.kind!='scored_history' or not isinstance(p,dict) or not p.get('scoring_hash'):
                    continue
                if p.get('schema_version')!=1 or p.get('week')!=snap.week or not p.get('game_ids'):
                    continue
                season=int(p['season'])
                for pid,points in p.get('points',{}).items():
                    info=catalog.get(pid,{})
                    position=info.get('position')
                    if position not in ('K','DEF','DST'):continue
                    key=(p['scoring_hash'],season)
                    contracts.setdefault(key,[]).append(dict(league_id=league.league_id,
                        scoring_hash=p['scoring_hash'],season=season,week=snap.week,
                        player_id=pid,position=position,points=points,rookie_verified=False))
            for (digest,season),rows in contracts.items():
                reports.append({'league_id':league.league_id,'scoring_hash':digest,
                    'source':'exact_league_scored_history','position_source':'current_provider_metadata',
                    **holdout(rows,holdout_season=season)})
    return {'reports':reports,'serving_promoted':False,
            'rookie_status':'requires_season_specific_rookie_cohort_not_inferred_from_current_metadata'}


if __name__=='__main__':print(json.dumps(asyncio.run(execute())))
