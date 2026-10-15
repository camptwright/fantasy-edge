from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Response

from src.services import workspace_background as bg
from src.services.forecast_evidence import digest
from src.models.governance import DerivedCheckpoint


def evidence():
    now=datetime.now(timezone.utc)
    data={'recipe_version':'model-a','read_model':{'generated_at':(now-timedelta(seconds=20)).isoformat(),
        'expires_at':(now+timedelta(minutes=2)).isoformat(),'input_revision':123}}
    payload={'recipe':'summary-v1','source_generated_at':data['read_model']['generated_at'],
        'source_revision':123,'source_model_version':'model-a','generated_at':now.isoformat(),
        'expires_at':data['read_model']['expires_at'],'data':{'status':'research','rows':[]}}
    return data,payload


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['source_time','revision','model','recipe','expired','future','source_future','digest','expires','malformed'])
async def test_cached_summary_withholds_source_version_or_time_mismatch(monkeypatch,change):
    monkeypatch.setattr(bg,'recipe',lambda:'summary-v1')
    data,payload=evidence()
    if change=='source_time':data['read_model']['generated_at']='2000-01-01T00:00:00+00:00'
    elif change=='revision':data['read_model']['input_revision']=124
    elif change=='model':data['recipe_version']='model-b'
    elif change=='recipe':payload['recipe']='old-code'
    elif change=='expired':
        payload['expires_at']=data['read_model']['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    elif change=='future':payload['generated_at']=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    elif change=='source_future':
        payload['source_generated_at']=data['read_model']['generated_at']=(datetime.now(timezone.utc)+timedelta(seconds=20)).isoformat()
    elif change=='expires':data['read_model']['expires_at']='2000-01-01T00:00:00+00:00'
    elif change=='malformed':payload['data']=42
    db=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(payload=payload,digest='bad' if change=='digest' else digest(payload))))
    assert await bg.cached(db,'L','standings',data) is None


@pytest.mark.asyncio
async def test_cached_summary_requires_intact_source_and_payload(monkeypatch):
    monkeypatch.setattr(bg,'recipe',lambda:'summary-v1')
    data,payload=evidence()
    db=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(payload=payload,digest=digest(payload))))
    assert await bg.cached(db,'L','standings',data)==payload['data']
    assert await bg.cached(db,'L','standings',None) is None
    assert await bg.cached(db,'L','standings',{}) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint,kind', [('league_standings','standings'),('trade_ideas','trade-ideas')])
async def test_get_routes_read_saved_summary_without_heavy_solver(monkeypatch,endpoint,kind):
    from src.api.routers import workspace
    monkeypatch.setattr(bg,'recipe',lambda:'summary-v1')
    data,payload=evidence()
    async def read(_db,_league):return deepcopy(data)
    def forbidden(*_args,**_kwargs):raise AssertionError('A GET attempted background computation')
    monkeypatch.setattr(workspace,'read',read)
    monkeypatch.setattr(workspace,'compute_standings',forbidden)
    monkeypatch.setattr(workspace,'compute_trade_ideas',forbidden)
    async def get(model,key):
        return SimpleNamespace(payload=payload,digest=digest(payload)) if model is DerivedCheckpoint else SimpleNamespace()
    db=SimpleNamespace(get=AsyncMock(side_effect=get))
    assert (await getattr(workspace,endpoint)('L',Response(),db)).status=='research'
    data['recipe_version']='new-model'
    assert (await getattr(workspace,endpoint)('L',Response(),db)).status=='updating'
