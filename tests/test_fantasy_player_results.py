from src.services.fantasy_player_results import espn_actuals
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from datetime import datetime, timezone
import pytest


def test_exact_actuals_only_and_no_inferred_zeroes():
    def stat(value, **extra):
        return dict(statSourceId=0, seasonId=2026, scoringPeriodId=2, appliedTotal=value, **extra)
    payload={'players':[
        {'player':{'id':1,'stats':[stat(0),stat(0)]}},
        {'player':{'id':2,'stats':[{**stat(99),'statSourceId':1},{**stat(10),'seasonId':2025}]}},
        {'player':{'id':3,'stats':[stat(-2)]}},
        {'player':{'id':4,'stats':[stat(1),stat(2)]}},
        {'player':{'id':5,'stats':[stat(True)]}},
        {'player':{'id':6,'stats':[{**stat(8),'scoringPeriodId':3}]}},
        {'player':{'id':7,'stats':[stat(99)]}},
    ]}
    result=espn_actuals(payload,season=2026,week=2,player_ids=range(1,7))
    assert result['points']=={'1':0.0,'3':-2.0}
    assert result['blockers']=={'2':'missing_exact_period_actual','4':'conflicting_actuals',
                                '5':'invalid_actual','6':'missing_exact_period_actual'}


@pytest.mark.parametrize('count,conflict,expected',[(10,False,'reconciled'),(9,False,'unreconciled'),(10,True,'unreconciled')])
async def test_pool_requires_corroborated_scores(count,conflict,expected):
    from src.services.fantasy_player_results import collect_espn_pool
    payload={'players':[{'player':{'id':i,'stats':[{'statSourceId':0,'seasonId':2026,
        'scoringPeriodId':2,'appliedTotal':i}]}} for i in range(count)]}
    client=AsyncMock();client.get.return_value=SimpleNamespace(raise_for_status=lambda:None,json=lambda:payload)
    points={str(i):i for i in range(count)}
    if conflict:points['0']=99
    with patch('src.ingest.espn_fantasy._snapshot',new_callable=AsyncMock) as save:
        result=await collect_espn_pool(None,client,league_id='espn:1',raw_league_id='1',
            season=2026,week=2,scoring={'x':1},rules={'items':[]},roster_points=points,
            game_ids=['g'],now=datetime.now(timezone.utc))
        assert result['status']==expected
        assert bool(result['points'])==(expected=='reconciled')
        assert save.call_args.args[3]=='historical_player_scores'
