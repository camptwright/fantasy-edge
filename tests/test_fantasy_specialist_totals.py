import pytest
from src.services.fantasy_specialist_totals import holdout


def rows():
    return [dict(league_id='l', scoring_hash='s', season=2026, week=w,
                 player_id=p, position=pos, points=v, rookie_verified=pos=='RB')
            for w in range(1, 6) for p,pos,v in [('k','K',4),('d','DEF',8),('r','RB',12)]]


def test_exact_total_cohorts_and_no_promotion():
    report=holdout(rows(),holdout_season=2026)
    assert not report['serving_promoted']
    assert all(v['n']==3 and v['candidate_mae']==0 for v in report['cohorts'].values())


def test_no_same_week_peer_or_future_leakage():
    data=rows()
    prefix=holdout([r for r in data if r['week']<5],holdout_season=2026)
    data += [dict(data[0],player_id='new',week=4,points=1000)]
    changed=holdout([r for r in data if r['week']<5],holdout_season=2026)
    assert prefix['cohorts']['kicker']['candidate_mae']==changed['cohorts']['kicker']['candidate_mae']


def test_missing_not_zero_and_no_unverified_rookie():
    data=rows()
    for r in data:
        r['rookie_verified']=False
        if r['week']==5:r['points']=None
    report=holdout(data,holdout_season=2026)
    assert report['cohorts']['rookie']['n']==0
    assert report['cohorts']['dst']['n']==2


def test_cross_league_duplicate_and_cross_rules_rejected():
    data=rows()
    with pytest.raises(ValueError,match='duplicate'):holdout(data+data[:1],holdout_season=2026)
    data[0]['scoring_hash']='different'
    with pytest.raises(ValueError,match='mixed'):holdout(data,holdout_season=2026)


def test_ros_requires_exact_contract_prior_history_and_dated_schedule():
    from datetime import datetime, timezone
    from types import SimpleNamespace as N
    from src.services.fantasy_specialist_totals import ros_research
    from src.services.fantasy_score_history import scoring_hash
    now=datetime(2026,10,9,tzinfo=timezone.utc)
    rules={'fgm':3}
    league=N(league_id='l',season='2026',platform='sleeper',scoring_settings=rules)
    snapshots=[N(league_id='l',kind='scored_history',week=w,synced_at=now,
        payload={'schema_version':1,'season':'2026','week':w,'scoring_hash':scoring_hash(rules),
                 'scoring_contract':rules,'points':{'k':6}}) for w in (1,2,5)]
    player={'player_id':'k','position':'K','ros':{'status':'complete_schedule_candidate'},
            'next_games':[{'kickoff':'2026-10-11T12:00:00Z'}]}
    def result():return ros_research([player],snapshots,league,{'k':{'position':'K'}},5,now)['k']
    assert result()['games']==2
    assert result()['conditional_ros_points']==6
    assert result()['serving_promoted'] is False
    player['next_games'][0]['kickoff']=None
    assert result()['conditional_ros_points']==6
    assert result()['horizon_status']=='complete_schedule_unknown_kickoffs'
    snapshots[0].payload['scoring_contract']={'fgm':4}
    assert result()['status']=='insufficient_history'
