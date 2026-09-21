"""College forecasts are captured now, never reconstructed from past results."""
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
from src.models.facts import Game, PlayerGameStat
from src.services.result_eligibility import no_pending_correction
from src.services.roster_stat_prospective import publish, candidates, grade_one


def records(report, now):
    # Reuse the fixed capture policy without implying verified injury status.
    if not timedelta(0)<=now-datetime.fromisoformat(report['generated_at'])<=timedelta(minutes=5): return []
    files=('college_player_lab.py','college_prospective.py','player_identity.py','roster_stat_model.py','roster_stat_prospective.py','lab_availability.py','injury_evidence.py')
    version=hashlib.sha256(b''.join((Path(__file__).parent/f).read_bytes() for f in files)).hexdigest()
    adapted={**report,'roster_synced_at':report['membership_fetched_at'],
             'players':[{**p,'injury_status':'unverified'} for p in report['players']]}
    output=candidates(adapted,now,version)
    for row in output:
        row['sport']='ncaaf'
        row['report_generated_at']=report['generated_at']
        row['membership_source']=report['membership_source']
    return output


async def execute():
    from scripts.evaluate_college_player_lab import evaluate
    root=Path(get_settings().raw_archive_dir)/'college-player-prospective'
    # A failed source refresh must not prevent correction-aware grading.
    report=None
    refresh_error=None
    try: report=await evaluate(full=True)
    except Exception as exc: refresh_error=type(exc).__name__
    async with get_worker_db() as db:
        await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        now=datetime.now(timezone.utc)
        proposed=records(report,now) if report else []
        existing=[json.loads(p.read_text()) for p in (root/'forecasts').glob('*.json')]
        ids={uuid.UUID(r['game_id']) for r in existing+proposed}
        games={str(g.id):g for g in (await db.scalars(select(Game).where(Game.id.in_(ids),Game.sport=='ncaaf'))).all()} if ids else {}
        new=0
        for row in proposed:
            game=games.get(row['game_id'])
            finished=datetime.now(timezone.utc)
            if not game or game.status!='scheduled' or not game.game_time or game.game_time<=finished+timedelta(minutes=5): continue
            if game.game_time.isoformat()!=row['kickoff']: continue
            row['captured_at']=finished.isoformat()
            if publish(root/'forecasts'/f"{row['id']}.json",row):
                existing.append(row)
                new+=1
        facts=(await db.scalars(select(PlayerGameStat).where(PlayerGameStat.game_id.in_(ids)))).all() if ids else []
        safe=set((await db.scalars(select(PlayerGameStat.id).where(PlayerGameStat.game_id.in_(ids),no_pending_correction()))).all()) if ids else set()
        values={(str(f.game_id),str(f.player_id),f.stat_type):f.value for f in facts}
        disputed={(str(f.game_id),str(f.player_id)) for f in facts if f.id not in safe}
        grades=[]
        for row in existing:
            key=(row['game_id'],row['player_id'],row['stat'])
            grades.append(grade_one(row,games.get(row['game_id']),values.get(key),key[:2] in disputed))
        groups=defaultdict(list)
        for grade in grades:
            if grade['status']=='graded': groups[(grade['version'],grade['stat'])].append(grade)
        metrics=[{'version':v,'stat':s,'n':len(rs),'baseline_mae':fmean(r['baseline_error'] for r in rs),
                  'workload_samples':sum(r.get('workload_error') is not None for r in rs),
                  'workload_paired_baseline_mae':fmean(r['baseline_error'] for r in rs if r.get('workload_error') is not None) if any(r.get('workload_error') is not None for r in rs) else None,
                  'availability_actions':dict(Counter(r.get('availability_shadow_action','not_captured') for r in rs)),
                  'workload_mae':fmean(r['workload_error'] for r in rs if r.get('workload_error') is not None) if any(r.get('workload_error') is not None for r in rs) else None,
                  'candidate_mae':fmean(r['candidate_error'] for r in rs)} for (v,s),rs in sorted(groups.items())]
        output={'status':'degraded' if refresh_error else 'experimental','generated_at':now.isoformat(),
            'refresh_error':refresh_error,'new_forecasts':new,'total_forecasts':len(existing),
            'counts':dict(Counter(g['status'] for g in grades)),'metrics':metrics,'grades':grades,'serving_enabled':False}
        publish(root/'reports'/f"{now.strftime('%Y%m%dT%H%M%S.%f')}-{uuid.uuid4().hex}.json",output)
        return {k:v for k,v in output.items() if k!='grades'}


def latest():
    paths=sorted((Path(get_settings().raw_archive_dir)/'college-player-prospective'/'reports').glob('*.json'))
    if not paths: return {'status':'not_started','metrics':[]}
    return {k:v for k,v in json.loads(paths[-1].read_text()).items() if k!='grades'}
