import pytest
from src.services.parlay_assistant import candidates,validate_selection

def offer(id='a',game='g1',**extra):
    return {'id':id,'game_id':game,'source':'draftkings','actionable':True,
            'model_probability':.6,'ev_percent':3,'price_american':-110,'selection':'Home',**extra}

def test_pool_excludes_ineligible_wrong_book_nonfinite_and_nonpositive_edges():
    rows=[offer(),offer('b',actionable=False),offer('c',source='pinnacle'),
          offer('d',model_probability=float('nan')),offer('e',ev_percent=-1),offer('f',game=None)]
    pool=candidates(rows,[],'draftkings');assert len(pool)==1
    assert pool[0]['id']=='a'

def test_selection_rejects_hallucinations_duplicates_and_same_games():
    pool=candidates([offer(),offer('b','g2'),offer('c','g1')],[],'draftkings')
    keys={p['id']:p['key'] for p in pool}
    assert len(validate_selection({'keys':[keys['a'],keys['b']]},pool,2))==2
    for bad in [['unknown',keys['b']],[keys['a'],keys['a']],[keys['a'],keys['c']],[],[None,keys['b']]]:
        with pytest.raises(ValueError):validate_selection({'keys':bad},pool,2)

def test_pool_is_bounded_and_props_retain_exact_side_and_book():
    assert len(candidates([offer(str(i),str(i)) for i in range(100)],[],'draftkings'))==40
    prop={'id':'p','game_id':'g','source':'draftkings','actionable':True,
          'model_probability':.6,'under_model_probability':.4,'over_price_american':110,
          'under_price_american':-120,'edge_percent':5,'under_edge_percent':-2}
    pool=candidates([],[prop],'draftkings')
    assert len(pool)==1 and pool[0]['side']=='over'


def test_provider_prefixes_resolve_to_exact_book_brand():
    for source in ['draftkings','sgo_draftkings','parlay_draftkings','theodds_draftkings']:
        pool=candidates([offer(source=source)],[],'draftkings')
        assert len(pool)==1 and pool[0]['source']==source
    assert candidates([offer(source='sgo_fanduel')],[],'draftkings')==[]


async def test_ai_transport_accepts_only_allowlisted_structured_output(monkeypatch):
    import httpx
    import json
    from types import SimpleNamespace
    from fastapi import HTTPException
    from src.services import parlay_assistant as service
    pool=candidates([offer(),offer('b','g2')],[],'draftkings')
    monkeypatch.setattr(service,'get_settings',lambda:SimpleNamespace(litellm_api_key='test',litellm_base_url='http://test/v1',fantasy_model_alias='test'))
    client=httpx.AsyncClient
    for keys,valid in [([r['key'] for r in pool],True),(['fabricated','offer'],False)]:
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'keys':keys})}}]}))
        monkeypatch.setattr(service.httpx,'AsyncClient',lambda **kwargs:client(transport=transport,**kwargs))
        if valid:assert len(await service.choose(pool,2,'test preferences'))==2
        else:
            with pytest.raises(HTTPException) as error:await service.choose(pool,2,'test')
            assert error.value.status_code==503


async def test_assistant_refuses_insufficient_pool_before_ai(monkeypatch):
    from src.api.routers import sportsbook
    from src.services import parlay_assistant
    async def empty(*args,**kwargs):return []
    async def forbidden(*args):raise AssertionError('AI called with no eligible offers')
    monkeypatch.setattr(sportsbook,'signal_rows',empty);monkeypatch.setattr(sportsbook,'prop_rows',empty)
    monkeypatch.setattr(parlay_assistant,'choose',forbidden)
    result=await sportsbook.assist_parlay(sportsbook.ParlayAssistantRequest(sport='nfl',book='draftkings'),None)
    assert result['ai_used'] is False and result['legs']==[]
