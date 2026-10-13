"""Content-addressed recovery copies; never rewrites frozen predictions."""
import hashlib
import json
from pathlib import Path
from datetime import datetime,timezone
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from src.models.governance import ForecastArchive
from src.utils import archive_io

KINDS=('forecasts','forecast_record','grading','grading_delta','shadow_entries','shadow_closes','missing_results','archive_index','capture_status')
GRADING_LATEST='forecast_grading:latest'
# Capture records are stored once by content (the record without its
# per-capture `prediction.last_seen_at`); a capture lists references in order.
RECORD_ENCODING='content_addressed_records_v1'


def split_record(record):
    """(body, last_seen_at or a missing marker) - the only field that changes on every capture."""
    prediction=record.get('prediction')
    if not isinstance(prediction,dict) or 'last_seen_at' not in prediction:
        return record,None
    body={**record,'prediction':{k:v for k,v in prediction.items() if k!='last_seen_at'}}
    return body,prediction['last_seen_at']


def compact_capture(payload):
    """(compact capture, {body digest: body}) - same order, same capture metadata."""
    bodies={};refs=[]
    for record in payload['records']:
        body,seen=split_record(record)
        key=digest(body);bodies[key]=body
        refs.append({'$body':key,**({'last_seen_at':seen} if seen is not None else {})})
    return {**payload,'records':refs,'record_encoding':RECORD_ENCODING},bodies


def expand_records(payload,bodies):
    """Rebuild a compact capture's full records; each body must match its digest."""
    if payload.get('record_encoding')!=RECORD_ENCODING:return payload
    records=[]
    for ref in payload['records']:
        body=bodies.get(ref['$body'])
        if body is None or digest(body)!=ref['$body']:raise ValueError('Forecast record body missing or altered')
        record=body
        if 'last_seen_at' in ref:
            record={**body,'prediction':{**body['prediction'],'last_seen_at':ref['last_seen_at']}}
        records.append(record)
    out={k:v for k,v in payload.items() if k!='record_encoding'}
    return {**out,'records':records}


async def record_bodies(db,keys):
    keys=sorted(set(keys));out={}
    for start in range(0,len(keys),500):
        rows=(await db.scalars(select(ForecastArchive).where(ForecastArchive.kind=='forecast_record',
            ForecastArchive.digest.in_(keys[start:start+500])))).all()
        out.update({r.digest:r.payload for r in rows})
    return out


async def expand_capture(db,payload):
    if payload.get('record_encoding')!=RECORD_ENCODING:return payload
    return expand_records(payload,await record_bodies(db,[r['$body'] for r in payload['records']]))


async def save_capture(db,payload):
    """Store bodies (deduplicated by digest) and the compact capture; returns the compact form."""
    compact,bodies=compact_capture(payload)
    for key,body in bodies.items():
        await db.execute(insert(ForecastArchive).values(digest=key,kind='forecast_record',payload=body).on_conflict_do_nothing())
    await save(db,'forecasts',compact)
    return compact,bodies


def digest(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


async def save(db,kind,payload):
    if kind not in KINDS:
        raise ValueError('Unsupported evidence kind')
    key=digest(payload)
    await db.execute(insert(ForecastArchive).values(digest=key,kind=kind,payload=payload).on_conflict_do_nothing())
    return key


def index_name(directory,kind):
    return 'archive_index:'+kind+':'+hashlib.sha256(str(Path(directory).resolve()).encode()).hexdigest()[:24]


async def save_index(db,name,payload):
    from datetime import datetime,timezone
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from src.models.governance import DerivedCheckpoint
    values={'name':name,'digest':digest(payload),'payload':payload,'updated_at':datetime.now(timezone.utc)}
    statement=pg_insert(DerivedCheckpoint).values(**values)
    await db.execute(statement.on_conflict_do_update(index_elements=['name'],
        set_={k:getattr(statement.excluded,k) for k in values if k!='name'}))


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
    # The file-signature index is a mutable cache (one row per directory/kind),
    # not evidence: appending a full copy per run grew quadratically
    # (1.55 GB of 1,332 copies by 2026-10-12). Legacy copies seed it once.
    from src.models.governance import DerivedCheckpoint
    name=index_name(directory,kind)
    row=await db.get(DerivedCheckpoint,name)
    if row is not None and digest(row.payload)==row.digest:
        index=row.payload.get('files',{})
    else:
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
    await save_index(db,name,{'directory':str(directory),'evidence_kind':kind,'files':checked})
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
        yield await expand_capture(db,row.payload) if kind=='forecasts' else row.payload


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


async def save_grading(db,payload):
    """History as a delta against the previous report; the full latest report in one mutable row."""
    from src.models.governance import DerivedCheckpoint
    from src.services import evidence_delta
    row=await db.get(DerivedCheckpoint,GRADING_LATEST)
    previous=row.payload if row is not None and digest(row.payload)==row.digest else await _legacy_latest(db)
    change=evidence_delta.delta(previous,payload,('reports','shadow_reports'))
    await save(db,'grading_delta',change)
    await save_index(db,GRADING_LATEST,payload)
    return change


async def _legacy_latest(db):
    row=await db.scalar(select(ForecastArchive).where(ForecastArchive.kind=='grading')
        .order_by(ForecastArchive.payload['graded_at'].astext.desc(),ForecastArchive.digest.desc()).limit(1))
    return row.payload if row is not None and digest(row.payload)==row.digest else None


async def latest_grade(db):
    from src.models.governance import DerivedCheckpoint
    latest=await db.get(DerivedCheckpoint,GRADING_LATEST)
    if latest is not None:
        if digest(latest.payload)!=latest.digest:return {'status':'unavailable','reports':[],'reason':'evidence_integrity_mismatch'}
        try:
            at=datetime.fromisoformat(latest.payload['graded_at'])
            stale=(datetime.now(timezone.utc)-at).total_seconds()>7200
        except (KeyError,ValueError,TypeError):return {'status':'unavailable','reports':[]}
        return {**latest.payload,'stale':stale,'evidence_store':'postgresql'}
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
