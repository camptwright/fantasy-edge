import json
from datetime import datetime,timezone
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from src.models.governance import ForecastArchive
from src.services.forecast_evidence import save,import_archives,payloads,restore,latest_grade
from src.services.forecast_grading import grade


def forecast():
    return {'schema_version':1,'captured_at':datetime.now(timezone.utc).isoformat(),
        'model_version':'test','records':[{'kind':'team','game_id':str(uuid4()),'market':'moneyline',
        'quote_id':'quote','side':'home','prediction':{'model_probability':.6,'sport':'nfl'}}]}


async def test_import_is_idempotent_and_grading_survives_archive_loss(db,tmp_path):
    p=forecast();path=tmp_path/'forecast.json';path.write_text(json.dumps(p))
    assert (await import_archives(db,tmp_path))['imported']==1
    assert (await import_archives(db,tmp_path))['imported']==0
    path.unlink() # Test-only loss simulation.
    report=await restore(db,tmp_path/'recovery')
    assert report['restored']==1 and report['integrity_verified']
    with pytest.raises(FileExistsError):await restore(db,tmp_path/'recovery')
    await db.rollback()
    result=await grade(db)
    assert result['raw_records']==1
    await db.rollback() # Grading transaction is read-only.
    await save(db,'grading',result);await db.commit()
    assert await db.scalar(select(func.count()).select_from(ForecastArchive).where(ForecastArchive.kind.in_(['forecasts','grading'])))==2
    assert (await latest_grade(db))['raw_records']==1


async def test_import_reports_partial_history_and_rejects_corruption(db,tmp_path):
    for i in range(2):(tmp_path/f'{i}.json').write_text(json.dumps(forecast()))
    first=await import_archives(db,tmp_path,limit=1)
    assert first=={'imported':1,'pending_files':1,'complete':False}
    assert (await import_archives(db,tmp_path,limit=1))['complete']
    row=await db.scalar(select(ForecastArchive).where(ForecastArchive.kind=='forecasts'))
    row.payload={**row.payload,'model_version':'tampered'}
    await db.commit()
    with pytest.raises(ValueError,match='integrity'):
        async for _ in payloads(db):pass


async def test_numeric_representation_survives_database_roundtrip(db):
    p=forecast();p['numeric_evidence']=[-0.0,1e20,1e-20,1.0]
    await save(db,'forecasts',p);await db.commit()
    rows=[r async for r in payloads(db)]
    assert rows==[p]


async def test_import_index_skips_unchanged_files_but_rechecks_changes(db,tmp_path,monkeypatch):
    from src.utils import archive_io
    path=tmp_path/'forecast.json'
    path.write_text(json.dumps(forecast()))
    await import_archives(db,tmp_path)
    original=archive_io.read_bytes
    reads=[]
    def read(p):
        reads.append(p)
        return original(p)
    monkeypatch.setattr(archive_io,'read_bytes',read)
    assert (await import_archives(db,tmp_path))['imported']==0
    assert reads==[]
    path.write_text(json.dumps(forecast()))
    assert (await import_archives(db,tmp_path))['imported']==1
    assert reads==[path]


def test_compact_grade_keeps_totals_and_pages_without_mutating_evidence():
    from src.services.forecast_evidence import compact_grade
    original={'counts':{'graded':200},'reports':[{'model_version':str(i)} for i in range(60)],
              'raw_records':200,'unresolved_evidence':{'items':list(range(25))},'large_shadow_array':[1]*100}
    small=compact_grade(original,limit=10,offset=10)
    assert small['reports']==original['reports'][10:20]
    assert small['next_offset']==20 and small['report_count']==60
    assert small['counts']=={'graded':200}
    assert 'large_shadow_array' not in small
    assert len(small['unresolved_evidence']['items'])==10
    assert len(original['unresolved_evidence']['items'])==25
