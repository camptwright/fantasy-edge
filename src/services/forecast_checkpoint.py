"""Incremental forecast selection without caching outcomes or changing cohorts.

Every source row's MVCC version is checked, including older imports. A changed
or removed source forces an integrity-checked full rebuild. Checkpoints store
each selected record once even when several shadow recipes refer to it.
"""
from datetime import datetime, timezone
from pathlib import Path
import base64
import json
import zlib
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from src.models.governance import ForecastArchive, DerivedCheckpoint
from src.services.forecast_evidence import digest

NAME='forecast-selection-v1'


def encode(payload):
    raw=json.dumps(payload,separators=(',',':'),allow_nan=False).encode()
    if len(raw)>256*1024*1024:raise ValueError('Checkpoint exceeds worker decode budget')
    compressed=base64.b64encode(zlib.compress(raw)).decode('ascii')
    if len(compressed)>64*1024*1024:raise ValueError('Checkpoint exceeds total storage budget')
    return {'encoding':'zlib-json-v1','data':compressed}


def decode(payload):
    if payload.get('encoding')!='zlib-json-v1':return payload
    decoder=zlib.decompressobj()
    raw=decoder.decompress(base64.b64decode(payload['data'],validate=True),256*1024*1024+1)
    if len(raw)>256*1024*1024 or not decoder.eof:
        raise ValueError('Invalid or oversized checkpoint')
    return json.loads(raw)


async def stored_payload(db,row):
    payload=row.payload
    if payload.get('encoding')!='chunked-zlib-json-v1':return payload
    chunks=[]
    for part in payload['parts']:
        item=await db.get(DerivedCheckpoint,part['name'])
        if item is None or item.digest!=part['digest'] or digest(item.payload)!=item.digest:
            raise ValueError('Derived forecast checkpoint chunk integrity mismatch')
        chunks.append(item.payload['data'])
    return {'encoding':'zlib-json-v1','data':''.join(chunks)}


async def write_checkpoint(db,name,payload):
    values={'name':name,'digest':digest(payload),'payload':payload,'updated_at':datetime.now(timezone.utc)}
    statement=insert(DerivedCheckpoint).values(**values)
    await db.execute(statement.on_conflict_do_update(index_elements=['name'],
        set_={k:getattr(statement.excluded,k) for k in values if k!='name'}))


async def persist_payload(db,payload):
    # Each database statement is <=1 MiB of compressed content. Publishing the
    # root and all parts in one transaction prevents partially visible states.
    data=payload['data'];parts=[]
    for index,start in enumerate(range(0,len(data),1024*1024)):
        part={'data':data[start:start+1024*1024]}
        name=f'{NAME}:part:{index}'
        await write_checkpoint(db,name,part)
        parts.append({'name':name,'digest':digest(part)})
    await write_checkpoint(db,NAME,{'encoding':'chunked-zlib-json-v1','parts':parts})


def recipe():
    from src.services.model_version import semantic_hash
    root=Path(__file__).parent
    return digest({name:semantic_hash((root/name).read_text()) for name in
        ('forecast_grading.py','forecast_checkpoint.py','stat_identity.py','prospective_review.py')})


def pack(state):
    cohort,raw,files,shadows=state
    records={}; objects={}
    def record_id(record):
        key=objects.get(id(record))
        if key is None:
            # Selection/grading needs frozen probabilities and contracts, not
            # multi-kilobyte feature/news/model diagnostics. Originals remain
            # immutable in forecast_archives for training and evidence review.
            compact={k:v for k,v in record.items() if k not in
                     ('feature_snapshot','inputs','context_experiment','injury_context')}
            fields=('model_probability','baseline_model_probability','market_fair_probability',
                    'fair_probability','forecast_eligible','actionable','sport',
                    'model_version','model_deployment_id')
            if 'prediction' in compact:
                compact['prediction']={k:v for k,v in compact['prediction'].items() if k in fields}
            key=digest(compact);objects[id(record)]=key;records[key]=compact
        return key
    def entries(rows,shadow=False):
        return [[list(key),value[0][0].isoformat(),value[0][1],record_id(value[1]),
                 *([value[2]] if shadow else [])] for key,value in rows.items()]
    selected=entries(cohort);extra=entries(shadows,True)
    return {'selected':selected,'shadows':extra,'records':records,'raw':raw,'files':files}


def unpack(payload):
    from src.services.forecast_grading import timestamp
    records=payload['records']
    def entries(rows):
        return {tuple(row[0]):((timestamp(row[1]),row[2]),records[row[3]],*row[4:]) for row in rows}
    return entries(payload['selected']),payload['raw'],payload['files'],entries(payload['shadows'])


async def load(db, *, persist=False):
    from src.services.forecast_grading import cohort_from_payloads
    # Caller supplies a repeatable-read transaction. Source identities and
    # bytes must be from the same database snapshot.
    versions=dict((await db.execute(text("SELECT digest, xmin::text FROM forecast_archives WHERE kind='forecasts' ORDER BY digest"))).all())
    current_recipe=recipe()
    checkpoint=await db.get(DerivedCheckpoint,NAME)
    previous={};state=({},0,0,{});modes={}
    valid=False
    if checkpoint is not None:
        if digest(checkpoint.payload)!=checkpoint.digest:
            raise ValueError('Derived forecast checkpoint integrity mismatch')
        prior=decode(await stored_payload(db,checkpoint))
        previous=prior.get('sources',{})
        valid=(prior.get('recipe')==current_recipe and
               all(versions.get(key)==value for key,value in previous.items()))
        if valid:
            state=unpack(prior['state']);modes=prior.get('selection_modes',{})
    if not valid:previous={}
    pending=sorted(set(versions)-set(previous))
    # Legacy/current policy mixtures can make the historical preference rule
    # order-dependent. Preserve the reference's digest order by rebuilding such
    # cohorts rather than guessing that an incremental merge is equivalent.
    from src.services.prospective_review import protocol
    from src.services.stat_identity import canonical_stat
    def note_modes(payload):
        version=payload.get('cohort_version',payload['model_version'])
        for record in payload['records']:
            p=record.get('prediction',{})
            v=p.get('model_version') if p.get('model_deployment_id') else version
            key=digest([v,record['game_id'],record['kind'],canonical_stat(record['market']),record.get('player_id')])
            mode=bool(record.get('prospective_protocol') and record['prospective_protocol']==protocol(p.get('sport')))
            modes[key]=sorted(set(modes.get(key,[]))|{mode})
    async def consume(keys,initial):
      for start in range(0,len(keys),100):
        rows=await db.stream(select(ForecastArchive).where(ForecastArchive.kind=='forecasts',
            ForecastArchive.digest.in_(keys[start:start+100])).order_by(ForecastArchive.digest)
            .execution_options(yield_per=1))
        async for archive in rows.scalars():
            if digest(archive.payload)!=archive.digest:
                raise ValueError('Forecast evidence integrity mismatch')
            note_modes(archive.payload)
            initial=cohort_from_payloads([archive.payload],include_shadows=True,state=initial)
      return initial
    state=await consume(pending,state)
    if pending and previous and any(len(values)>1 for values in modes.values()):
        pending=sorted(versions);previous={};modes={}
        state=await consume(pending,({},0,0,{}))
    if persist and (pending or not valid):
        payload=encode({'recipe':current_recipe,'sources':versions,'state':pack(state),'selection_modes':modes})
        await persist_payload(db,payload)
    return state,{'archives_processed':len(pending),'archives_reused':len(previous),'checkpoint_valid':valid}


async def refresh(db):
    await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
    # A duplicate refresh can wait; a serialization conflict retries next run.
    await db.execute(text('SELECT pg_advisory_xact_lock(79431801)'))
    _,report=await load(db,persist=True)
    await db.commit()
    return report
