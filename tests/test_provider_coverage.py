from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N
from unittest.mock import AsyncMock
import pytest
from src.services.provider_coverage import coverage

@pytest.mark.asyncio
async def test_dedup_and_explicit_quote_gates():
    now=datetime.now(timezone.utc)
    game=N(sport='nfl',status='scheduled',game_time=now+timedelta(days=1))
    quote=N(source='test_book',game_id='g',player_id='p',stat_type='yards',line=20,observed_at=now)
    fresh=N(seen_at=now,available=True)
    other=N(**{**quote.__dict__,'player_id':'q'})
    stale=N(seen_at=now-timedelta(hours=1),available=True)
    db=N(execute=AsyncMock(return_value=N(all=lambda:[(quote,game,fresh),(quote,game,fresh),(other,game,stale)])))
    result=await coverage(db)
    assert result['rows_scanned']==3
    assert result['groups'][0]['offers']==2
    assert result['groups'][0]['quote_eligible']==1
    assert result['groups'][0]['blockers']=={'offer_stale':1}

@pytest.mark.asyncio
async def test_empty_is_not_provider_failure():
    db=N(execute=AsyncMock(return_value=N(all=lambda:[])))
    result=await coverage(db)
    assert result['groups']==[]
    assert not result['truncated']
