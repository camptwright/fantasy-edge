from copy import deepcopy
from src.services.college_lab_view import compact


def fixture():
    return {'status':'experimental','players':[
        {'player_id':str(i),'name':f'Player {i:03}','team':'Texas Longhorns' if i<120 else 'Other','stats':[{'candidate':i}]} for i in range(125)],
        'coverage':{'players':125},'metrics':[{'samples':400}],'serving_enabled':False}


def test_bounded_default_preserves_full_metrics_and_original():
    original=fixture();before=deepcopy(original);view=compact(original)
    assert original==before
    assert len(view['players'])==50
    assert view['selected_team']=='Texas Longhorns'
    assert view['pagination']=={'offset':0,'limit':50,'total':120,'all_players':125,'next_offset':50}
    assert view['metrics']==original['metrics'] and view['coverage']==original['coverage']
    assert view['serving_enabled'] is False


def test_paging_is_stable_complete_and_does_not_change_predictions():
    report=fixture();rows=[]
    for offset in (0,50,100):rows.extend(compact(report,offset=offset)['players'])
    assert rows==report['players'][:120]
    assert compact(report,offset=100)['pagination']['next_offset'] is None
    assert len(compact(report,limit=1000)['players'])==100
    assert len(compact(report,team='Other')['players'])==5


def test_unknown_team_or_empty_page_does_not_silently_show_other_players():
    assert compact(fixture(),team='Unknown')['players']==[]
    assert compact(fixture(),offset=999)['players']==[]
    empty=compact({'status':'not_started','players':[],'metrics':[]})
    assert empty['selected_team'] is None and empty['pagination']['total']==0


async def test_api_keeps_full_contract_unless_compact_is_requested(monkeypatch):
    from src.api.routers.nfl_predictor import college_players
    from src.services import college_player_lab, college_prospective
    report=fixture();evidence={'status':'experimental','metrics':[],'total_forecasts':42}
    monkeypatch.setattr(college_player_lab,'latest',lambda:report)
    monkeypatch.setattr(college_prospective,'latest',lambda:evidence)
    full=await college_players(compact=False,team=None,offset=0,limit=50)
    assert full=={**report,'prospective':evidence}
    small=await college_players(compact=True,team='Other',offset=0,limit=2)
    assert len(small['players'])==2 and small['pagination']['total']==5
    assert small['prospective']==evidence
