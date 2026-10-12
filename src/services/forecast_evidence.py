"""Content-addressed recovery copies; never rewrites frozen predictions."""
import hashlib
import json
from pathlib import Path
from datetime import datetime,timezone
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from src.models.governance import ForecastArchive
from src.utils import archive_io

KINDS=('forecasts','grading','shadow_entries','shadow_closes','missing_results','archive_index','capture_status')


def digest(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


async def save(db,kind,payload):
    if kind not in KINDS:
        raise ValueError('Unsupported evidence kind')
    key=digest(payload)
    await db.execute(insert(ForecastArchive).values(digest=key,kind=kind,payload=payload).on_conflict_do_nothing())
    return key


async def import_archives(db,directory,*,limit=100,kind='forecasts'):
    """Bound parsing of new files; verified unchanged files use a durable index.

    Metadata is only an optimization for previously content-hashed files whose
    digest is still present in the evidence store. Changed files are rehashed.
    Stored forecast payloads retain their independent integrity checks.
    """
    if kind not in KINDS:raise ValueError('Unsupported evidence kind')
    if limit<1:raise ValueError('Import limit must be positive')
    known=set((await db.scalars(select(ForecastArchive.digest).where(ForecastArchive.kind==kind))).all())
    directory=Path(directory).resolve()
    previous=await db.scalar(select(ForecastArchive).where(ForecastArchive.kind=='archive_index',
        ForecastArchive.payload['directory'].astext==str(directory),
        ForecastArchive.payload['evidence_kind'].astext==kind)
        .order_by(ForecastArchive.created_at.desc(),ForecastArchive.digest.desc()).limit(1))
    index=previous.payload.get('files',{}) if previous and digest(previous.payload)==previous.digest else {}
    checked={}
    imported=0;pending=0
    for path in archive_io.files(directory):
        if path.is_symlink():raise ValueError('Symlink forecast archive refused')
        stat=path.stat()
        signature=[stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns]
        cached=index.get(path.name,{})
        if cached.get('signature')==signature and cached.get('digest') in known:
            checked[path.name]=cached
            continue
        if imported>=limit:
            pending+=1
            continue
        payload=archive_io.read_json(path)
        key=digest(payload)
        after=path.stat()
        if signature!=[after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns]:
            pending+=1
            continue
        checked[path.name]={'signature':signature,'digest':key}
        if key in known:continue
        await save(db,kind,payload)
        known.add(key);imported+=1
    await save(db,'archive_index',{'directory':str(directory),'evidence_kind':kind,'files':checked})
    await db.commit()
    return {'imported':imported,'pending_files':pending,'complete':pending==0}


async def repair_legacy_json(db,directory):
    """One-time repair from originals after JSONB normalized number spellings.

    Requires the original content hash AND semantically identical DB contents.
    No prediction values can change through this repair.
    """
    repaired=0
    for path in archive_io.files(directory):
        if path.is_symlink():raise ValueError('Symlink forecast archive refused')
        original=archive_io.read_json(path);key=digest(original)
        row=await db.get(ForecastArchive,(key,'forecasts'))
        if row is None or digest(row.payload)==key:continue
        if row.payload!=original:raise ValueError('Original and stored forecast differ semantically')
        from sqlalchemy import update
        await db.execute(update(ForecastArchive).where(ForecastArchive.digest==key,
            ForecastArchive.kind=='forecasts').values(payload=original))
        repaired+=1
    await db.commit()
    return {'repaired_numeric_representation':repaired}


async def payloads(db,kind='forecasts'):
    # Stream large history instead of loading all raw snapshots at once.
    rows=await db.stream(select(ForecastArchive).where(ForecastArchive.kind==kind).order_by(ForecastArchive.digest).execution_options(yield_per=1))
    async for row in rows.scalars():
        if digest(row.payload)!=row.digest:
            raise ValueError('Forecast evidence integrity mismatch')
        yield row.payload


async def restore(db,directory,*,kind='forecasts'):
    """Restore to a NEW directory only; never overwrite the live archive."""
    if kind not in KINDS:raise ValueError('Unsupported evidence kind')
    from src.services.roster_stat_prospective import publish
    target=Path(directory)
    target.mkdir(parents=False,exist_ok=False)
    count=0
    rows=await db.stream(select(ForecastArchive).where(ForecastArchive.kind==kind).execution_options(yield_per=1))
    async for row in rows.scalars():
        if digest(row.payload)!=row.digest:raise ValueError('Forecast evidence integrity mismatch')
        path=target/f'{row.digest}.json'
        publish(path,row.payload)
        if digest(json.loads(path.read_text()))!=row.digest:raise ValueError('Restored evidence integrity mismatch')
        count+=1
    return {'restored':count,'kind':kind,'directory':str(target),'integrity_verified':True}


async def latest_grade(db):
    row=await db.scalar(select(ForecastArchive).where(ForecastArchive.kind=='grading')
        .order_by(ForecastArchive.payload['graded_at'].astext.desc(),ForecastArchive.digest.desc()).limit(1))
    if row is None:return {'status':'awaiting_grading','reports':[]}
    if digest(row.payload)!=row.digest:return {'status':'unavailable','reports':[],'reason':'evidence_integrity_mismatch'}
    try:
        at=datetime.fromisoformat(row.payload['graded_at'])
        stale=(datetime.now(timezone.utc)-at).total_seconds()>7200
    except (KeyError,ValueError,TypeError):return {'status':'unavailable','reports':[]}
    return {**row.payload,'stale':stale,'evidence_store':'postgresql'}


async def capture_status(db):
    row=await db.scalar(select(ForecastArchive).where(ForecastArchive.kind=='capture_status')
        .order_by(ForecastArchive.created_at.desc(),ForecastArchive.digest.desc()).limit(1))
    if row is None or digest(row.payload)!=row.digest:
        return {'status':'unknown','stale':True,'captured_at':None}
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(row.payload['captured_at'])).total_seconds()
    return {**row.payload,'status':'current' if 0<=age<=1800 else 'overdue',
            'stale':not 0<=age<=1800,'age_seconds':round(age)}


def compact_grade(payload,limit=50,offset=0):
    """Presentation-only pagination; full immutable evidence stays available."""
    fields=('status','graded_at','stale','raw_records','cohort_records','duplicates_excluded',
            'counts','note','evidence_store','latest_selected_capture_at')
    result={k:payload[k] for k in fields if k in payload}
    reports=payload.get('reports',[])
    report_fields=('sport','kind','market','model_version','sample_size','independent_games',
                   'brier_score','paired_baseline_brier','paired_baseline_samples','log_loss','counts')
    result.update(reports=[{k:r[k] for k in report_fields if k in r} for r in reports[offset:offset+limit]],report_count=len(reports),
                  offset=offset,limit=limit,next_offset=offset+limit if offset+limit<len(reports) else None)
    evidence=payload.get('unresolved_evidence')
    if evidence:
        result['unresolved_evidence']={**evidence,'items':evidence.get('items',[])[:10],
            'truncated':evidence.get('truncated',False) or len(evidence.get('items',[]))>10}
    return result
