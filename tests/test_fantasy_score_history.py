from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS
from src.services.fantasy_score_history import exact_totals, distributions, scoring_hash
from src.services.fantasy_simulation import eligibility_reasons
from unittest.mock import AsyncMock, patch
import pytest


def test_duplicate_conflicting_missing_and_negative_totals():
    rows=[{'players_points':{'K':0,'DEF':-2,'bad':1,'missing':None}},
          {'players_points':{'K':0,'bad':2,'bool':True}}]
    assert exact_totals(rows)=={'K':0.0,'DEF':-2.0}


def test_eight_weeks_same_rules_season_and_no_lookahead():
    now=datetime.now(timezone.utc); scoring={'rec':1}
    rows=[NS(kind='scored_history',week=i,synced_at=now-timedelta(days=1),
        payload={'schema_version':1,'season':'2026','scoring_hash':scoring_hash(scoring),'points':{'BAL':i}})
        for i in range(1,10)]
    assert distributions(rows,scoring,2026,8,now)['BAL']['score_samples']==[]
    assert distributions(rows,scoring,2026,9,now)['BAL']['score_samples']==list(range(1,9))
    assert distributions(rows,{'rec':.5},2026,9,now)=={}
    assert distributions(rows,scoring,2025,9,now)=={}
    rows[0].synced_at=now+timedelta(days=1)
    assert distributions(rows,scoring,2026,9,now)['BAL']['score_samples']==[]


def test_explicit_healthy_and_nonfinite_values():
    p=dict(locked=False,weekly_points=10,weekly_evidence={'status':'pregame_provider_projection'},
        injury_status='Active',score_samples=[0,10]*4)
    assert eligibility_reasons(p)==[]
    assert 'availability_review_required' in eligibility_reasons({**p,'injury_status':'Questionable'})
    assert 'invalid_projection' in eligibility_reasons({**p,'weekly_points':float('nan')})


async def test_espn_requests_completed_period_and_daily_pacing():
    from src.services.fantasy_score_history import collect_espn
    now=datetime.now(timezone.utc)
    game=NS(id='game-1',week=1,status='final',game_time=now-timedelta(days=3))
    db=AsyncMock();db.scalars.return_value=NS(all=lambda:[game]);db.get.return_value=None
    rules={'scoringItems':[{'statId':1,'points':1}]};scoring={'x':1}
    current={'settings':{'scoringSettings':rules},'scoringPeriodId':3,'teams':[]}
    historical={'settings':{'scoringSettings':rules},'scoringPeriodId':1,
        'schedule':[{'id':10,'matchupPeriodId':1,'home':{'teamId':2,'totalPoints':-2}}], 'teams':[
        {'id':2,'roster':{'entries':[{'playerPoolEntry':{'player':{'id':1,'stats':[
            {'statSourceId':0,'scoringPeriodId':1,'seasonId':2026,'appliedTotal':-2},
            {'statSourceId':1,'scoringPeriodId':1,'seasonId':2026,'appliedTotal':99}]}}}]}}]}
    client=AsyncMock();client.get.return_value=NS(raise_for_status=lambda:None,json=lambda:historical)
    with patch('src.services.fantasy_schedule.coverage',return_value={'complete':True}), \
         patch('src.services.fantasy_player_results.collect_espn_pool',new_callable=AsyncMock), \
         patch('src.ingest.espn_fantasy._snapshot',new_callable=AsyncMock) as save:
        assert (await collect_espn(db,'espn:1',2026,scoring,current,now,client=client,raw_league_id='1'))['weeks']==1
        assert ('scoringPeriodId',1) in client.get.call_args.kwargs['params']
        assert save.call_args.args[-1]['points']=={'1':-2.0}
        refreshed=next(c.args[-1] for c in save.call_args_list if c.args[-2]=='matchups')
        assert refreshed[0]['players_points']=={'1':-2.0}
        assert refreshed[0]['points']==-2
        db.get.return_value=NS(payload=save.call_args.args[-1],synced_at=now)
        client.reset_mock()
        assert (await collect_espn(db,'espn:1',2026,scoring,current,now,client=client,raw_league_id='1'))['weeks']==0
        client.get.assert_not_called()
        # A missing player-pool archive must not be hidden by fresh roster
        # history. Once written it shares the existing daily pacing.
        fresh=db.get.return_value
        db.get.side_effect=lambda model,key: None if key[-1]=='historical_player_scores' else fresh
        assert (await collect_espn(db,'espn:1',2026,scoring,current,now,client=client,raw_league_id='1'))['weeks']==1
        db.get.side_effect=None
        # Fresh scored history alone must not suppress repair of a stale
        # compatibility snapshot used by weekly/provider grading.
        history=db.get.return_value
        db.get.side_effect=lambda model,key: history if key[-1]=='scored_history' else NS(
            payload=[{'roster_id':2,'starters':['1']}],synced_at=now-timedelta(days=3))
        save.reset_mock()
        assert (await collect_espn(db,'espn:1',2026,scoring,current,now,client=client,raw_league_id='1'))['weeks']==1
        refreshed=next(c.args[-1] for c in save.call_args_list if c.args[-2]=='matchups')
        assert refreshed[0]['starters']==['1']
        assert refreshed[0]['players_points']=={'1':-2.0}
        db.get.side_effect=None
        db.get.return_value=None
        historical['scoringPeriodId']=2
        with pytest.raises(ValueError):
            await collect_espn(db,'espn:1',2026,scoring,current,now,client=client,raw_league_id='1')
