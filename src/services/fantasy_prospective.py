"""Immutable fantasy point forecasts; no reconstructed pregame performance."""
import hashlib
import json
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import fmean
from sqlalchemy import select, text
from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot
from src.models.facts import Game, PlayerGameStat
from src.services.result_eligibility import no_pending_correction
from src.services.roster_stat_prospective import publish
from src.services.fantasy_decision_models import build
from src.services.roster_stat_model import finite
from src.services.projection_identity import manifest, reference, archive_identity
from src.utils import archive_io


def version():
    return manifest()['cohort_version']


def candidates(lab,now,v):
    if lab.get('status')!='candidate' or lab['coverage']['stale_inputs']: return []
    result=[]
    for p in lab['players']:
        h=p['ros']['per_game']
        if h.get('status') not in ('candidate','partial_scoring') or not p.get('canonical_player_id'): continue
        for game in p['next_games']:
            if not game['kickoff'] or game['status']!='scheduled': continue
            kickoff=datetime.fromisoformat(game['kickoff'])
            if not timedelta(minutes=5)<kickoff-now<=timedelta(hours=72): continue
            identity=f"{v}:{lab['league_id']}:{game['id']}:{p['canonical_player_id']}:{json.dumps(lab['scoring_settings'],sort_keys=True)}"
            result.append({'id':hashlib.sha256(identity.encode()).hexdigest(),'version':v,'kind':'player_game',
                'league_id':lab['league_id'],'captured_at':now.isoformat(),'game_id':game['id'],
                'kickoff':game['kickoff'],'player_id':p['canonical_player_id'],'platform_player_id':p['player_id'],
                'name':p['name'],'prediction':h,'scoring_settings':lab['scoring_settings'],
                'scoring_cohort':hashlib.sha256(json.dumps(h['scoring_weights'],sort_keys=True).encode()).hexdigest(),
                'ros_at_capture':p['ros'],'remaining_schedule':p['next_games']})
    return result


def grade(record,game,values,disputed=False):
    base={k:record[k] for k in ('id','version','league_id','scoring_cohort')}
    if game is None: return {**base,'status':'missing_game'}
    if str(game.id)!=record.get('game_id'):return {**base,'status':'game_binding_mismatch'}
    if not game.game_time or datetime.fromisoformat(record['captured_at'])>=game.game_time:
        return {**base,'status':'invalid_capture_time'}
    if game.status!='final': return {**base,'status':'awaiting_final'}
    if disputed: return {**base,'status':'pending_correction'}
    weights=record['prediction']['scoring_weights']
    missing=sorted(k for k in weights if not finite(values.get(k)))
    if missing: return {**base,'status':'missing_scoring_results','missing':missing,
        'result_blocker':'missing_player_results' if not values else 'missing_scoring_categories'}
    actual=sum(values[k]*w for k,w in weights.items())
    return {**base,'status':'graded','actual':actual,
        'scoring_status':record['prediction']['status'],
        'baseline_error':abs(actual-record['prediction']['baseline_subtotal']),
        'candidate_error':abs(actual-record['prediction']['modeled_subtotal'])}


async def grade_with_recovery(db,record,game,values,disputed,identities,snapshots):
    """Same correction-safe grading path for individual and ROS components."""
    result=grade(record,game,values,disputed)
    if result['status']!='missing_scoring_results' or record['league_id'].startswith('espn:'):
        return result
    from src.services.fantasy_result_recovery import recover
    from src.services.fantasy_component_history import ARCHIVE_ID, PREFIX
    keys=((ARCHIVE_ID,game.week,PREFIX+str(game.season)),(record['league_id'],game.week,'scored_history'))
    for key in keys:
        if key not in snapshots:snapshots[key]=await db.get(SleeperLeagueSnapshot,key)
    player=identities.get(record.get('platform_player_id'))
    recovered=recover(record,game,snapshots[keys[0]],snapshots[keys[1]],
        identity_matches=player is not None and str(player.id)==record['player_id'],existing_values=values)
    return recovered if recovered['status']=='graded' else {**result,'recovery_blocker':recovered.get('reason',recovered['status'])}


async def grade_ros_parts(db,record,games,values,disputed,identities,snapshots):
    parts=[]
    for scheduled in record['remaining_schedule']:
        gid=scheduled['id'];key=(gid,record['player_id'])
        # Rebind only an evaluation copy. The archived horizon and forecast stay immutable.
        part={**record,'game_id':gid}
        parts.append(await grade_with_recovery(db,part,games.get(gid),values.get(key,{}),
            key in disputed,identities,snapshots))
    return parts


async def capture_forecasts(db,root,leagues,identity):
    """Capture policy is versioned independently of grading/report generation."""
    v=identity['cohort_version']; new=0; errors={}
    for league in leagues:
        lab=await build(db,league.league_id)
        now=datetime.now(timezone.utc)
        from src.services.fantasy_weekly_evidence import candidates as provider_candidates
        for record in provider_candidates(lab,now):
            publish(root/'provider-weekly'/f"{record['id']}.json",{**record,'model_identity':reference(identity)})
        for record in candidates(lab,now,v):
            record={**record,'model_identity':reference(identity)}
            new+=publish(root/'forecasts'/f"{record['id']}.json",record)
            remaining=[g for g in record['remaining_schedule'] if g['kickoff'] is None or datetime.fromisoformat(g['kickoff'])>now]
            if record['ros_at_capture'].get('full_ros_value') is not None and remaining:
                rid=hashlib.sha256(f"ros:{v}:{league.league_id}:{league.season}:{record['player_id']}:{record['scoring_cohort']}".encode()).hexdigest()
                publish(root/'ros'/f'{rid}.json',{**record,'id':rid,'remaining_schedule':remaining,'kind':'ros'})
        if lab.get('status')=='candidate' and lab['coverage']['weekly_decisions_open']:
            kickoffs=[g['kickoff'] for g in lab['validation_lineups']['games']]
            if kickoffs and all(kickoffs) and timedelta(minutes=5)<min(datetime.fromisoformat(k) for k in kickoffs)-now<=timedelta(hours=72):
                key=hashlib.sha256(f"weekly:{v}:{league.league_id}:{league.season}:{lab['week']}".encode()).hexdigest()
                from src.services.fantasy_lineup_validation import frozen
                experiment=frozen(lab)
                if experiment:
                    key=hashlib.sha256((key+':lineup-experiment').encode()).hexdigest()
                publish(root/'weekly'/f'{key}.json',{'id':key,'version':v,'captured_at':now.isoformat(),
                    'league_id':league.league_id,'week':lab['week'],'matchup':lab['matchup'],
                    'lineup_experiment':experiment,'model_identity':reference(identity),
                    'lineups':lab['validation_lineups'],'waivers':lab['waivers']})
        if lab.get('status')!='candidate' or lab['coverage']['stale_inputs']:
            errors[league.league_id]='stale_or_missing_inputs'
    return new,errors


async def execute():
    root=Path(get_settings().raw_archive_dir)/'fantasy-prospective'
    identity=manifest()
    archive_identity(root,identity)
    async with get_worker_db() as db:
        await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        leagues=(await db.scalars(select(SleeperLeague).where(SleeperLeague.sport=='nfl'))).all()
        new,errors=await capture_forecasts(db,root,leagues,identity)
        records=[json.loads(p.read_text()) for p in (root/'forecasts').glob('*.json')]
        ros_records=[json.loads(p.read_text()) for p in (root/'ros').glob('*.json')]
        weekly=[json.loads(p.read_text()) for p in (root/'weekly').glob('*.json')]
        ids={uuid.UUID(r['game_id']) for r in records}|{uuid.UUID(g['id']) for r in ros_records for g in r['remaining_schedule']}|{uuid.UUID(g['id']) for r in weekly for g in r['lineups']['games']}
        games={str(g.id):g for g in (await db.scalars(select(Game).where(Game.id.in_(ids)))).all()} if ids else {}
        facts=(await db.scalars(select(PlayerGameStat).where(PlayerGameStat.game_id.in_(ids)))).all() if ids else []
        safe=set((await db.scalars(select(PlayerGameStat.id).where(PlayerGameStat.game_id.in_(ids),no_pending_correction()))).all()) if ids else set()
        values=defaultdict(dict); disputed=set()
        for f in facts:
            key=(str(f.game_id),str(f.player_id)); values[key][f.stat_type]=f.value
            if f.id not in safe: disputed.add(key)
        from src.services.player_identity import resolve_platform_players
        from src.services.fantasy_component_history import ARCHIVE_ID, PREFIX
        recovery_targets=[r for r in records+ros_records if not r['league_id'].startswith('espn:')]
        identities=await resolve_platform_players(db,'sleeper',
            {r.get('platform_player_id') for r in recovery_targets if r.get('platform_player_id')}) if recovery_targets else {}
        snapshots={}
        grades=[await grade_with_recovery(db,r,games.get(r['game_id']),values[(r['game_id'],r['player_id'])],
            (r['game_id'],r['player_id']) in disputed,identities,snapshots) for r in records]
        groups=defaultdict(list)
        for g in grades:
            if g['status']=='graded': groups[(g['version'],g['league_id'],g['scoring_cohort'])].append(g)
        metrics=[{'version':v,'league_id':l,'scoring_cohort':s,'n':len(rs),
            'baseline_mae':fmean(r['baseline_error'] for r in rs),'candidate_mae':fmean(r['candidate_error'] for r in rs)}
            for (v,l,s),rs in groups.items()]
        ros_grades=[]
        for r in ros_records:
            parts=await grade_ros_parts(db,r,games,values,disputed,identities,snapshots)
            complete=bool(parts) and all(p['status']=='graded' for p in parts)
            actual=sum(p['actual'] for p in parts) if complete else None
            ros_grades.append({'id':r['id'],'status':'graded' if complete else 'awaiting_complete_results',
                'component_counts':dict(Counter(p['status'] for p in parts)),'actual':actual,
                'candidate_error':abs(actual-r['ros_at_capture']['full_ros_value']) if complete else None,
                'baseline_error':abs(actual-r['prediction']['baseline_subtotal']*len(parts)) if complete else None})
        weekly_grades=[]
        for r in weekly:
            gs=[games.get(g['id']) for g in r['lineups']['games']]
            if not gs or any(g is None or g.status!='final' for g in gs):
                weekly_grades.append({'id':r['id'],'status':'awaiting_final'}); continue
            if any(not g.game_time or datetime.fromisoformat(r['captured_at'])>=g.game_time for g in gs):
                weekly_grades.append({'id':r['id'],'status':'invalid_capture_time'}); continue
            snapshot=await db.get(SleeperLeagueSnapshot,(r['league_id'],r['week'],
                'scored_history' if r.get('lineup_experiment') else 'matchups'))
            if not snapshot or snapshot.synced_at<max(g.game_time for g in gs)+timedelta(hours=24):
                weekly_grades.append({'id':r['id'],'status':'awaiting_final_platform_snapshot'});continue
            from src.services.fantasy_score_history import exact_totals,scoring_hash
            league=next((l for l in leagues if l.league_id==r['league_id']),None)
            if r.get('lineup_experiment') and (not league or scoring_hash(league.scoring_settings,
                league.raw.get('scoringSettings') if league.platform=='espn' else None)!=r['lineup_experiment']['scoring_hash']):
                weekly_grades.append({'id':r['id'],'status':'scoring_rules_changed'});continue
            if r.get('lineup_experiment') and snapshot.payload.get('scoring_hash')!=r['lineup_experiment']['scoring_hash']:
                weekly_grades.append({'id':r['id'],'status':'unbound_result_scoring_rules'});continue
            point_rows=snapshot.payload if snapshot and isinstance(snapshot.payload,list) else []
            points=snapshot.payload['points'] if r.get('lineup_experiment') else exact_totals(point_rows)
            recovery=None
            if r.get('lineup_experiment') and league.platform=='sleeper':
                from src.services.fantasy_component_history import ARCHIVE_ID, PREFIX
                from src.services.fantasy_sleeper_results import recover_lineup_points
                archive=await db.get(SleeperLeagueSnapshot,(ARCHIVE_ID,r['week'],PREFIX+str(league.season)))
                points,recovery=recover_lineup_points(r,snapshot,archive,games)
            from src.services.fantasy_lineup_validation import grade as grade_simulation
            weekly_grades.append({**grade_weekly(r,points),'version':r['version'],
                'league_id':r['league_id'],'week':r['week'],'result_recovery':recovery,'lineup_experiment':grade_simulation(r,points)})
        simulation_groups=defaultdict(list)
        for row in weekly_grades:
            if row.get('lineup_experiment',{}).get('status')=='graded':
                simulation_groups[(row['version'],row['league_id'])].append(row['lineup_experiment'])
        simulation_metrics=[{'version':v,'league_id':league_id,'n':len(rows),
            'current_brier':fmean(r['current']['brier'] for r in rows),
            'candidate_brier':fmean(r['candidate']['brier'] for r in rows),
            'coinflip_brier':fmean(r['current']['coinflip_brier'] for r in rows),
            'serving_promoted':False} for (v,league_id),rows in simulation_groups.items()]
        from src.services.fantasy_weekly_evidence import grade as grade_provider
        provider_grades=[]; provider_records=[]
        for path in (root/'provider-weekly').glob('*.json'):
            record=json.loads(path.read_text())
            provider_records.append(record)
            game=await db.get(Game,uuid.UUID(record['game_id']))
            snapshot=await db.get(SleeperLeagueSnapshot,(record['league_id'],record['week'],'matchups'))
            result=grade_provider(record,game,snapshot)
            if not record['league_id'].startswith('espn:') and result.get('result_blocker')=='player_absent_from_platform_results' and game is not None:
                from src.services.fantasy_sleeper_results import grade_components
                from src.services.fantasy_component_history import ARCHIVE_ID, PREFIX
                components=await db.get(SleeperLeagueSnapshot,(ARCHIVE_ID,record['week'],PREFIX+str(game.season)))
                official=await db.get(SleeperLeagueSnapshot,(record['league_id'],record['week'],'scored_history'))
                result=grade_components(record,game,components,official)
            if record['league_id'].startswith('espn:') and record.get('scoring_contract_hash'):
                from src.services.fantasy_weekly_evidence import grade_archive
                archive=await db.get(SleeperLeagueSnapshot,(record['league_id'],record['week'],'historical_player_scores'))
                result=grade_archive(record,game,archive)
            provider_grades.append(result)
        from src.services.fantasy_evidence_counts import provider_counts, lineup_counts, result_backlog
        report={'generated_at':datetime.now(timezone.utc).isoformat(),'status':'experimental','new_forecasts':new,
            'evaluation_identity':reference(identity),
            'provider_weekly':{'forecasts':len(provider_grades),'counts':dict(Counter(g['status'] for g in provider_grades)),
                'observation_counts':provider_counts(provider_records,provider_grades),
                'positions':dict(Counter(g['position'] for g in provider_grades)),'grades':provider_grades},
            'total_forecasts':len(records),'counts':dict(Counter(g['status'] for g in grades)),
            'result_backlog':result_backlog(records,grades),
            'metrics':metrics,'grades':grades,'capture_blocks':errors,'serving_enabled':False,
            'lineup_experiments':{'forecasts':sum(bool(r.get('lineup_experiment')) for r in weekly),
                'evidence_status':lineup_counts(weekly,weekly_grades,version()),
                'metrics':simulation_metrics,'serving_promoted':False},
            'ros':{'forecasts':len(ros_records),'counts':dict(Counter(g['status'] for g in ros_grades)),'grades':ros_grades},
            'weekly':{'forecasts':len(weekly),'counts':dict(Counter(g['status'] for g in weekly_grades)),'grades':weekly_grades}}
        publish(root/'reports'/f"{report['generated_at']}-{uuid.uuid4().hex}.json",report)
        return {k:v for k,v in report.items() if k!='grades'}


def grade_weekly(record,points):
    def total(ids): return sum(points[p] for p in ids) if ids and all(p in points for p in ids) else None
    a=total(record['lineups']['your_starters']); b=total(record['lineups']['opponent_starters'])
    actual=a-b if a is not None and b is not None else None
    projected=record['matchup'].get('projected_margin')
    waivers=[]
    before_ids=[x['player_id'] for x in record['waivers'].get('before',{}).get('lineup',[])]
    before=total(before_ids)
    for move in record['waivers']['moves']:
        after=total([x['player_id'] for x in move['after_lineup']])
        waivers.append({'add_id':move['add_id'],'status':'graded' if before is not None and after is not None else 'missing_player_points',
            'realized_lineup_gain':after-before if before is not None and after is not None else None})
    return {'id':record['id'],'status':'graded' if actual is not None and projected is not None else 'missing_player_points',
        'margin_actual':actual,'margin_error':abs(actual-projected) if actual is not None and projected is not None else None,'waivers':waivers}


def latest():
    paths=archive_io.files(Path(get_settings().raw_archive_dir)/'fantasy-prospective'/'reports')
    if not paths: return {'status':'not_started'}
    report={k:v for k,v in archive_io.read_json(paths[-1]).items() if k!='grades'}
    for kind in ('ros','weekly','provider_weekly'):
        if kind in report: report[kind]={k:v for k,v in report[kind].items() if k!='grades'}
    return report
