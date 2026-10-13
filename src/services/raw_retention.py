"""Bounded, dry-run-first retention for redundant result observations, plus
lossless daily compression of append-only archive directories."""
import json
import gzip
import hashlib
import os
import tempfile
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


# Append-only directories of timestamp-named files (archive()/timestamped
# publish()) that nothing existence-checks. ~95% of raw growth (2026-10-12:
# ~16 GB/week; gzip 14-26x on these). Never add a directory of create-only
# identity records: their first-observation-wins check reads the exact
# `.json` path, so compressing one would allow a hindsight re-capture.
# Every reader of these directories goes through src.utils.archive_io.
COMPRESSIBLE=('result-observations','roster-evidence','grading','grading/deltas','forecasts','mlb_availability',
    'espn_injuries','aggregate-props','fantasy-scoring-source','college-player-lab',
    'fantasy-prospective/reports')


def compress_daily(*,now=None,min_age=timedelta(days=1),max_bytes=2*1024**3,root=None):
    """Losslessly gzip day-old direct files in COMPRESSIBLE, oldest first, within a byte budget."""
    now=now or utcnow();base=Path(root or get_settings().raw_archive_dir)
    candidates=[]
    for name in COMPRESSIBLE:
        directory=base/name
        if directory.is_symlink() or not directory.is_dir():continue
        for path in directory.glob('*.json'):
            # `_latest.json` is a mutable pointer, not history: never compress it.
            if path.is_symlink() or not path.is_file() or path.name.startswith('_'):continue
            info=path.stat()
            if info.st_mtime<(now-min_age).timestamp():candidates.append((info.st_mtime,info.st_size,path,directory))
    candidates.sort()
    done=[];budget=0;remaining=0
    for _,size,path,directory in candidates:
        if budget+size>max_bytes and done:
            remaining+=1;continue
        try:result=compress_verified(path,directory)
        except (OSError,ValueError) as exc:
            done.append({'path':str(path),'status':'skipped','reason':type(exc).__name__});continue
        budget+=size;done.append(result)
    return {'status':'lossless_compression_complete','policy':'append_only_daily_gzip_v1',
        'compressed':sum(r['status']=='compressed' for r in done),
        'skipped':sum(r['status']!='compressed' for r in done),
        'bytes_read':budget,'bytes_saved':sum(r.get('bytes_saved',0) for r in done),
        'remaining_files':remaining,'deleted':0}


def compress_verified(path,root):
    """Lossless retention: replace one immutable JSON with verified gzip bytes."""
    path=Path(path);root=Path(root)
    if root.is_symlink() or path.is_symlink() or path.parent.resolve()!=root.resolve():
        raise ValueError('Retention path escaped the direct archive directory')
    target=path.with_suffix('.json.gz')
    if target.exists():return {'status':'already_compressed','bytes_saved':0}
    with path.open('rb') as source:
        before=os.fstat(source.fileno())
        original=source.read()
    key=hashlib.sha256(original).hexdigest()
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=root,prefix='.retention-',delete=False) as stream:
            temporary=Path(stream.name)
            with gzip.GzipFile(fileobj=stream,mode='wb',mtime=0) as zipped:zipped.write(original)
            stream.flush();os.fsync(stream.fileno())
        with gzip.open(temporary,'rb') as recovered:
            if hashlib.sha256(recovered.read()).hexdigest()!=key:raise ValueError('Compressed recovery hash mismatch')
        current=path.lstat()
        if (current.st_ino,current.st_size,current.st_mtime_ns)!=(before.st_ino,before.st_size,before.st_mtime_ns):
            raise ValueError('Archive changed during compression')
        os.link(temporary,target) # Never overwrite an existing recovery copy.
        directory_fd=os.open(root,os.O_RDONLY)
        try:os.fsync(directory_fd)
        finally:os.close(directory_fd)
        path.unlink()
        return {'status':'compressed','path':str(target),'sha256':key,
            'bytes_saved':max(0,before.st_size-target.stat().st_size)}
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


async def retain(db,**kwargs):
    """Recompute eligibility now; never execute a user-supplied path manifest."""
    report=await plan(db,**kwargs)
    root=Path(get_settings().raw_archive_dir)/'result-observations'
    items=[compress_verified(row['path'],root) for row in report['candidates']]
    return {**report,'status':'lossless_retention_complete','compressed':sum(r['status']=='compressed' for r in items),
        'bytes_saved':sum(r['bytes_saved'] for r in items),'recovery_copies':items,
        'note':'Eligible original JSON replaced by hash-verified gzip; no evidence is discarded. Restore with gzip decompression.'}
