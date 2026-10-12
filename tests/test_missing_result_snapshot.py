from datetime import datetime, timezone, timedelta
from src.services.forecast_evidence import save
from src.services.missing_result_queue import queue


async def test_missing_snapshot_is_not_reported_as_complete(db):
    result=await queue(db)
    assert result['status']=='awaiting_snapshot' and result['total'] is None


async def test_snapshot_pagination_and_freshness(db):
    await save(db,'missing_results',{'generated_at':(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(),
        'items':[{'id':i} for i in range(5)],'total':5,'counts':{'missing_stat_category':5}})
    await db.commit()
    result=await queue(db,limit=2,offset=2)
    assert result['items']==[{'id':2},{'id':3}]
    assert result['next_offset']==4 and result['stale'] and result['total']==5
