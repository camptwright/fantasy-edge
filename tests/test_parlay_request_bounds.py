from uuid import uuid4
import pytest
from pydantic import ValidationError
from src.api.routers.sportsbook import ParlayBuildRequest, build_parlay


def test_parlay_request_size_is_bounded():
    with pytest.raises(ValidationError):ParlayBuildRequest(legs=[])
    with pytest.raises(ValidationError):ParlayBuildRequest(legs=[{'kind':'prop','id':uuid4()} for _ in range(9)])


async def test_prop_builder_loads_only_selected_latest_ids(monkeypatch):
    from src.api.routers import sportsbook
    chosen=uuid4();seen=[]
    async def props(db,sport,**kwargs):seen.append(kwargs['quote_ids']);return []
    async def signals(*args,**kwargs):raise AssertionError('Unrequested signal work')
    monkeypatch.setattr(sportsbook,'prop_rows',props)
    monkeypatch.setattr(sportsbook,'signal_rows',signals)
    result=await build_parlay(ParlayBuildRequest(legs=[{'kind':'prop','id':chosen}]),None)
    assert seen==[{chosen}]
    assert len(result['skipped_legs'])==1
