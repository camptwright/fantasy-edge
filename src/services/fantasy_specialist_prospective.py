"""Immutable, pregame, exact-league specialist research; never serving promotion.

Score each forecast origin separately by horizon. Missing outcomes never become
zero. Conditional constant-role season totals are not participation forecasts.
"""
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean

from sqlalchemy import select, or_, text
from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.facts import Game
from src.models.identity import Team
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot
from src.services.fantasy_specialist_totals import ros_research
from src.services.retention_pipeline import digest, outcomes, publish_latest
from src.services.roster_stat_prospective import publish
from src.services.roster_stat_model import finite

RECIPE='specialist_prospective_constant_role_v1'


def recipe_hash():
    return digest({name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ('fantasy_specialist_totals.py','fantasy_specialist_prospective.py','retention_pipeline.py')})


def freeze(lab, league, snapshots, games, teams, now):
    if lab.get('status')!='candidate' or lab.get('coverage',{}).get('stale_inputs'):
        return [], {'stale_or_missing_model':1}
    metadata=sorted((s for s in snapshots if s.kind=='player_metadata'
        and s.league_id==league.league_id and s.synced_at<=now),key=lambda s:s.synced_at)
    catalog=metadata[-1].payload if metadata else {}
    estimates=ros_research(lab['players'],snapshots,league,catalog,lab['week'],now)
    aliases={'LA':'LAR','JAC':'JAX','WSH':'WAS'}
    team_index=defaultdict(list)
    for t in teams:team_index[aliases.get(t.nflverse_abbr,t.nflverse_abbr)].append(str(t.id))
    game_index={str(g.id):g for g in games}
    records=[]; blockers=Counter()
    for p in lab['players']:
        estimate=estimates.get(p['player_id'])
        if not estimate or not finite(estimate.get('points')):continue
        tids=team_index[aliases.get(p.get('team'),p.get('team'))]
        if len(tids)!=1:
            blockers['unresolved_team']+=1;continue
        bound=[]
        for item in p.get('next_games',[]):
            g=game_index.get(item['id'])
            if (not g or g.sport!='nfl' or str(g.season)!=str(league.season)
                or g.game_type!='REG' or g.week not in range(lab['week'],19)
                or tids[0] not in (str(g.home_team_id),str(g.away_team_id))
                or g.status!='scheduled' or not g.game_time or g.game_time<=now+timedelta(minutes=5)):
                blockers['unbound_or_started_game']+=1;continue
            bound.append(g)
        bound.sort(key=lambda g:g.week)
        if len({g.week for g in bound})!=len(bound):
            blockers['ambiguous_team_week']+=1;continue
        # One-game and dated-season horizons are distinct research targets.
        horizons=[[g] for g in bound]
        if len(bound)>1 and len(bound)==len(p.get('next_games',[])):
            horizons.append(bound)
        for horizon in horizons:
            key={'recipe':RECIPE,'recipe_hash':recipe_hash(),'model_version':lab['recipe_version'],
                'league_id':league.league_id,'season':str(league.season),'player_id':p['player_id'],
                'origin_week':lab['week'],'game_ids':[str(g.id) for g in horizon],
                'scoring_contract':estimate['scoring_hash']}
            records.append({**key,'id':digest(key),'captured_at':now.isoformat(),
                'cohort':estimate['cohort'],'horizon_games':len(horizon),
                'candidate_points':estimate['points']*len(horizon),
                'baseline_points':estimate['baseline']*len(horizon),
                'training_games':estimate['games'],'serving_promoted':False,
                'scope':'conditional_constant_role_not_participation_probability',
                'player_games':{str(g.week):{p['player_id']:{'game_id':str(g.id),
                    'kickoff':g.game_time.isoformat(),'team_id':tids[0]}} for g in horizon}})
    return records,dict(blockers)


def grade(record, snapshots, games, now):
    captured=datetime.fromisoformat(record['captured_at'])
    if any(captured>=datetime.fromisoformat(e['kickoff']) for week in record['player_games'].values() for e in week.values()):
        return {'status':'invalid_postgame_capture'}
    values=outcomes(record,snapshots,games,now)
    expected=[(int(w),pid) for w,players in record['player_games'].items() for pid in players]
    if not expected or len(expected)!=record['horizon_games']:
        return {'status':'invalid_horizon'}
    if any(key not in values for key in expected):
        return {'status':'awaiting_complete_horizon','observed_games':sum(k in values for k in expected)}
    actual=sum(values[k]['points'] for k in expected)
    return {'status':'graded','actual_points':actual,
        'candidate_error':abs(actual-record['candidate_points']),
        'baseline_error':abs(actual-record['baseline_points']),
        'outcomes':[values[k] for k in expected]}


async def run_league(db, lab, league, root, *, now=None):
    now=now or datetime.now(timezone.utc);root=Path(root)
    snapshots=list((await db.scalars(select(SleeperLeagueSnapshot).where(SleeperLeagueSnapshot.league_id==league.league_id))).all())
    games=list((await db.scalars(select(Game).where(Game.sport=='nfl',Game.season==int(league.season),or_(Game.game_type.is_(None),Game.game_type=='REG')))).all())
    teams=list((await db.scalars(select(Team).where(Team.sport=='nfl'))).all())
    records,blockers=freeze(lab,league,snapshots,games,teams,now)
    written=sum(publish(root/'forecasts'/f"{r['id']}.json",r) for r in records)
    grades=[];groups=defaultdict(list)
    for path in sorted((root/'forecasts').glob('*.json')):
        r=json.loads(path.read_text())
        if r['league_id']!=league.league_id or r['season']!=str(league.season):continue
        result=grade(r,snapshots,games,now)
        grades.append({'id':r['id'],'recipe_hash':r['recipe_hash'],**result})
        if result['status']=='graded':groups[(r['recipe_hash'],r['cohort'],r['horizon_games'],r['model_version'],r['scoring_contract'])].append(result)
    metrics=[{'recipe_hash':k[0],'cohort':k[1],'horizon_games':k[2],
        'model_version':k[3],'scoring_contract':k[4],'n':len(v),
        'candidate_mae':fmean(x['candidate_error'] for x in v),
        'baseline_mae':fmean(x['baseline_error'] for x in v)} for k,v in groups.items()]
    report={'league_id':league.league_id,'season':str(league.season),'generated_at':now.isoformat(),'recipe':RECIPE,
        'new_captures':written,'capture_blockers':blockers,'grades':grades,'metrics':metrics,
        'serving_promoted':False,'qualification':'independent_outcomes_and_review_required'}
    publish(root/'reports'/f"{now.strftime('%Y%m%dT%H%M%S%f')}-{league.league_id.replace(':','_')}.json",report)
    publish_latest(root,report)
    return report


async def execute():
    from src.services.fantasy_decision_models import build
    root=Path(get_settings().raw_archive_dir)/'fantasy-specialist-prospective'
    async with get_worker_db() as db:
        await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        leagues=list((await db.scalars(select(SleeperLeague).where(SleeperLeague.sport=='nfl'))).all())
        return [await run_league(db,await build(db,l.league_id),l,root) for l in leagues]
