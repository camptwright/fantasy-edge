"""Immutable first-window forecasts and repeatable current-result grading.

Archives are separate from production. Atomic no-overwrite publication makes
retries and overlapping workers harmless. Never pool errors across stat units.
"""
import hashlib
import json
import os
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean

from sqlalchemy import select, text
from config.settings import get_settings
from src.models.facts import Game, PlayerGameStat
from src.services.result_eligibility import no_pending_correction
from src.services.roster_stat_lab import build
from src.services.roster_stat_model import finite, RECIPE


def version():
    files = ('roster_stat_model.py', 'roster_stat_lab.py', 'roster_stat_prospective.py', 'player_identity.py','lab_availability.py','injury_evidence.py')
    return hashlib.sha256(b''.join((Path(__file__).parent/f).read_bytes() for f in files)).hexdigest()


def publish(path, payload):
    """Atomic create-only, including under concurrent execution."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{uuid.uuid4().hex}.tmp')
    try:
        with temporary.open('x') as stream:
            json.dump(payload, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
            return True
        except FileExistsError:
            return False
    finally:
        temporary.unlink(missing_ok=True)


def candidates(lab, now, model_version):
    if lab['status'] != 'experimental': return []
    synced = datetime.fromisoformat(lab['roster_synced_at'])
    if not timedelta(0) <= now-synced <= timedelta(hours=6): return []
    records = []
    for player in lab['players']:
        if not player.get('player_id') or not player.get('game_id') or not player.get('game_time'): continue
        kickoff = datetime.fromisoformat(player['game_time'])
        if not timedelta(minutes=5) < kickoff-now <= timedelta(hours=72): continue
        for stat in player['stats']:
            if stat['status'] != 'ready' or not all(finite(stat.get(k)) for k in ('baseline','candidate')): continue
            key = hashlib.sha256(f"{model_version}:{player['game_id']}:{player['player_id']}:{stat['stat']}".encode()).hexdigest()
            records.append({'id': key, 'version': model_version, 'recipe': RECIPE,
                'captured_at': now.isoformat(), 'kickoff': player['game_time'],
                'game_id': player['game_id'], 'player_id': player['player_id'],
                'name': player['name'], 'position': player['position'], 'stat': stat['stat'],
                'roster_synced_at': lab['roster_synced_at'], 'injury_label': player['injury_status'],
                'prediction': stat, 'policy': 'first_eligible_72h_to_5min_v1'})
            records[-1]['availability_candidate']=player.get('availability_candidate',{})
    return records


def grade_one(record, game, value, correction_pending=False):
    result = {'id': record['id'], 'version': record['version'], 'stat': record['stat']}
    if game is None: return {**result, 'status': 'missing_game'}
    if game.game_time is None or datetime.fromisoformat(record['captured_at']) >= game.game_time:
        return {**result, 'status': 'invalid_capture_time'}
    if game.status != 'final': return {**result, 'status': 'awaiting_final'}
    if correction_pending: return {**result, 'status': 'pending_correction'}
    if not finite(value): return {**result, 'status': 'missing_result'}
    prediction = record['prediction']
    workload=prediction.get('workload_candidate',{})
    return {**result, 'status': 'graded', 'actual': value,
        'workload_error':abs(workload['mean']-value) if workload.get('status')=='ready' else None,
        'availability_shadow_action':record.get('availability_candidate',{}).get('shadow_action','not_captured'),
        'baseline_error': abs(prediction['baseline']-value),
        'candidate_error': abs(prediction['candidate']-value),
        'historical_range_contains_result': prediction['historical_low'] <= value <= prediction['historical_high']}


async def run(db, root=None):
    root = Path(root or get_settings().raw_archive_dir)/'nfl-player-prospective'
    # Stable history and correction view throughout this run. Known kickoff is
    # deliberately required by the prospective eligibility policy.
    await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
    first = await build(db)
    labs = [first]
    for league in first['leagues']:
        if league['id'] != first.get('league_id'): labs.append(await build(db, league['id']))
    now, model_version = datetime.now(timezone.utc), version()
    new = sum(publish(root/'forecasts'/f"{r['id']}.json", r)
              for lab in labs for r in candidates(lab, now, model_version))
    records = [json.loads(p.read_text()) for p in sorted((root/'forecasts').glob('*.json'))]
    ids = {uuid.UUID(r['game_id']) for r in records}
    games = {str(g.id): g for g in (await db.scalars(select(Game).where(Game.id.in_(ids)))).all()} if ids else {}
    values, eligible = {}, set()
    if ids:
        rows = (await db.scalars(select(PlayerGameStat).where(PlayerGameStat.game_id.in_(ids)))).all()
        safe = (await db.scalars(select(PlayerGameStat.id).where(PlayerGameStat.game_id.in_(ids), no_pending_correction()))).all()
        safe = set(safe)
        for row in rows:
            key = (str(row.game_id), str(row.player_id), row.stat_type)
            values[key] = row.value
            if row.id in safe: eligible.add(key)
    grades = []
    for record in records:
        key = (record['game_id'], record['player_id'], record['stat'])
        grades.append(grade_one(record, games.get(record['game_id']), values.get(key), key in values and key not in eligible))
    grouped = defaultdict(list)
    for grade in grades:
        if grade['status'] == 'graded': grouped[(grade['version'], grade['stat'])].append(grade)
    metrics = [{'version': v, 'stat': s, 'n': len(rows),
        'baseline_mae': fmean(r['baseline_error'] for r in rows),
        'candidate_mae': fmean(r['candidate_error'] for r in rows),
        'workload_samples':sum(r.get('workload_error') is not None for r in rows),
        'workload_paired_baseline_mae':fmean(r['baseline_error'] for r in rows if r.get('workload_error') is not None) if any(r.get('workload_error') is not None for r in rows) else None,
        'availability_actions':dict(Counter(r.get('availability_shadow_action','not_captured') for r in rows)),
        'workload_mae':fmean(r['workload_error'] for r in rows if r.get('workload_error') is not None) if any(r.get('workload_error') is not None for r in rows) else None,
        'historical_range_coverage': fmean(r['historical_range_contains_result'] for r in rows)}
        for (v, s), rows in sorted(grouped.items())]
    report = {'status': 'experimental', 'generated_at': now.isoformat(), 'new_forecasts': new,
        'total_forecasts': len(records), 'counts': dict(Counter(g['status'] for g in grades)),
        'metrics': metrics, 'grades': grades, 'serving_enabled': False,
        'note': 'First eligible forecast per model/player/game/stat. Missing results are not zero. Grades are recomputed against current corrected finals; earlier grading reports remain archived.'}
    publish(root/'reports'/f"{now.strftime('%Y%m%dT%H%M%S.%f')}-{uuid.uuid4().hex}.json", report)
    return {k: v for k, v in report.items() if k != 'grades'}


def latest():
    paths = sorted((Path(get_settings().raw_archive_dir)/'nfl-player-prospective'/'reports').glob('*.json'))
    if not paths: return {'status': 'not_started', 'metrics': []}
    report = json.loads(paths[-1].read_text())
    return {k:v for k,v in report.items() if k != 'grades'}
