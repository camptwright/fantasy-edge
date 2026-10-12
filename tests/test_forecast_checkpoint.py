from datetime import datetime,timezone,timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select, text
from src.models.governance import ForecastArchive,DerivedCheckpoint
from src.services.forecast_evidence import save
from src.services.forecast_checkpoint import refresh,load,NAME
from src.services.forecast_grading import cohort_from_payloads
from src.services.forecast_evidence import digest


def forecast(gid,at,quote,p=.6):
    return {'schema_version':1,'captured_at':at.isoformat(),'model_version':'v1','records':[
        {'kind':'team','game_id':gid,'market':'moneyline','side':'home','quote_id':quote,
         'prediction':{'model_probability':p,'sport':'nfl'},
         'shadow_predictions':{'candidate':{'model_probability':.7,'recipe_version':'r1'}}}]}


async def test_incremental_matches_full_with_late_earlier_import(db):
    gid=str(uuid4());now=datetime.now(timezone.utc)
    first=forecast(gid,now,'z');earlier=forecast(gid,now-timedelta(hours=1),'a')
    await save(db,'forecasts',first);await db.commit()
    assert (await refresh(db))['archives_processed']==1
    assert (await refresh(db))['archives_processed']==0
    await save(db,'forecasts',earlier);await db.commit()
    assert (await refresh(db))['archives_processed']==1
    await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
    state,info=await load(db)
    assert state==cohort_from_payloads([first,earlier],True)
    assert info['archives_processed']==0


async def test_checkpoint_detects_source_mutation_and_cache_corruption(db):
    payload=forecast(str(uuid4()),datetime.now(timezone.utc),'a')
    await save(db,'forecasts',payload);await db.commit()
    await refresh(db)
    row=await db.scalar(select(ForecastArchive).where(ForecastArchive.kind=='forecasts'))
    row.payload={**payload,'model_version':'tampered'}
    await db.commit()
    with pytest.raises(ValueError,match='Forecast evidence integrity'):
        await refresh(db)
    await db.rollback()
    checkpoint=await db.get(DerivedCheckpoint,NAME)
    checkpoint.payload={**checkpoint.payload,'recipe':'tampered'}
    await db.commit()
    with pytest.raises(ValueError,match='checkpoint integrity'):
        await refresh(db)


async def test_mixed_policy_late_import_matches_reference_order(db):
    from src.services.prospective_review import protocol
    now=datetime.now(timezone.utc);gid=str(uuid4())
    a=forecast(gid,now,'a');b=forecast(gid,now+timedelta(minutes=1),'b')
    c=forecast(gid,now-timedelta(minutes=1),'c')
    for payload,verified in ((a,False),(b,True)):
        payload['records'][0]['prospective_protocol']=protocol('nfl')
        payload['records'][0]['prediction']['forecast_eligible']=verified
        await save(db,'forecasts',payload)
    await db.commit();await refresh(db)
    await save(db,'forecasts',c);await db.commit();await refresh(db)
    actual,_=await load(db)
    expected=cohort_from_payloads(sorted([a,b,c],key=digest),True)
    assert actual==expected


def test_compressed_checkpoint_preserves_numeric_evidence():
    from src.services.forecast_checkpoint import encode,decode
    payload={'numbers':[-0.0,1e-20,1e20],'records':['repeated']*1000}
    encoded=encode(payload)
    assert digest(decode(encoded))==digest(payload)
    assert len(encoded['data'])<1000


async def test_chunk_storage_roundtrip_is_bounded_and_rollback_is_atomic(db):
    from src.services.forecast_checkpoint import persist_payload, stored_payload
    original={'encoding':'zlib-json-v1','data':'a'*(1024*1024+17)}
    await persist_payload(db,original)
    await db.commit()
    root=await db.get(DerivedCheckpoint,NAME)
    assert len(root.payload['parts'])==2
    assert await stored_payload(db,root)==original
    for part in root.payload['parts']:
        row=await db.get(DerivedCheckpoint,part['name'])
        assert len(row.payload['data'])<=1024*1024
    await persist_payload(db,{'encoding':'zlib-json-v1','data':'replacement'})
    await db.rollback()
    db.expire_all()
    root=await db.get(DerivedCheckpoint,NAME)
    assert await stored_payload(db,root)==original


@pytest.mark.parametrize('failure',['missing','modified','rehashed'])
async def test_chunk_integrity_rejects_missing_or_changed_parts(db,failure):
    from src.services.forecast_checkpoint import persist_payload, stored_payload, encode
    await persist_payload(db,encode({'evidence':'original'}))
    await db.commit()
    root=await db.get(DerivedCheckpoint,NAME)
    part=await db.get(DerivedCheckpoint,root.payload['parts'][0]['name'])
    if failure=='missing':
        await db.delete(part)
    else:
        part.payload={'data':'tampered'}
        if failure=='rehashed':part.digest=digest(part.payload)
    await db.commit()
    with pytest.raises(ValueError,match='chunk integrity mismatch'):
        await stored_payload(db,root)
