"""Bounded, dry-run-first retention for redundant result observations only."""
import json
from datetime import datetime,timedelta
from pathlib import Path
from sqlalchemy import select
from config.settings import get_settings
from src.models.base import utcnow
from src.models.facts import Game,PlayerGameStat
from src.models.governance import ResultCorrection,ResultSyncState


def eligible(payload,state,game,protected_hashes,cutoff,durable):
    if (not isinstance(payload,dict) or not state or state.status!='succeeded' or
        not game or game.status!='final' or not game.game_time or game.game_time>=cutoff or not durable):
        return False
    try: observed=datetime.fromisoformat(payload['observed_at'])
    except (KeyError,TypeError,ValueError):return False
    return (observed.tzinfo is not None and observed<cutoff and
        bool(payload.get('payload_hash')) and payload['payload_hash'] not in protected_hashes and
        observed<state.last_attempt_at)


async def plan(db,*,now=None,days=90,max_files=500,max_bytes=256*1024*1024):
    if days<90:raise ValueError('Minimum raw result retention is 90 days')
    now=now or utcnow();cutoff=now-timedelta(days=days)
    root=Path(get_settings().raw_archive_dir)/'result-observations'
    corrections=(await db.scalars(select(ResultCorrection))).all()
    protected={h for c in corrections for h in (c.first_payload_hash,c.last_payload_hash) if h}
    states={(str(s.game_id),s.provider):s for s in (await db.scalars(select(ResultSyncState))).all()}
    games={str(g.id):g for g in (await db.scalars(select(Game))).all()}
    durable={str(g) for g in (await db.scalars(select(PlayerGameStat.game_id).distinct())).all()}
    current_paths=set()
    for state in states.values():
        try:
            detail=json.loads(state.detail or '{}')
            if detail.get('evidence_archive'):current_paths.add(str(Path(detail['evidence_archive']).resolve()))
        except (ValueError,TypeError):continue
    candidates=[];scanned=0;read_bytes=0
    # Only direct JSON files in one exact directory. No symlink traversal,
    # forecasts, receipts, models, correction evidence, weather or settlements.
    if root.is_symlink():raise ValueError('Symlink retention root refused')
    for path in sorted(root.glob('*.json')):
        if path.is_symlink() or not path.is_file() or str(path.resolve()) in current_paths:continue
        info=path.stat()
        if info.st_mtime>=cutoff.timestamp():continue
        if scanned>=max_files or read_bytes+info.st_size>max_bytes:break
        scanned+=1;read_bytes+=info.st_size
        try:payload=json.loads(path.read_text())
        except (OSError,ValueError,UnicodeError):continue
        if not isinstance(payload,dict):continue
        key=(payload.get('game_id'),payload.get('provider'))
        if eligible(payload,states.get(key),games.get(key[0]),protected,cutoff,key[0] in durable):
            candidates.append({'path':str(path),'bytes':info.st_size,'payload_hash':payload['payload_hash']})
    return {'status':'dry_run','policy':'redundant_results_90d_v1','days':days,'scanned':scanned,
        'candidate_bytes':sum(r['bytes'] for r in candidates),'candidates':candidates,'deleted':0,
        'protected':'Latest sync evidence, all correction hashes, unresolved games and durable research archives.',
        'note':'No automatic deletion enabled; inspect the manifest before authorizing an execution policy.'}
