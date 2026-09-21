from datetime import datetime,timezone,timedelta
from src.services.fantasy_specialists import candidate,holdout,weights


def rows():
    return [{'season':2024 if i<8 else 2025,'week':i+1 if i<8 else i-7,
             'time':datetime(2024,1,1,tzinfo=timezone.utc)+timedelta(days=7*i),
             'player_id':'k','game_id':str(i),'values':{'fantasy_pat_made':i%3}}
            for i in range(12)]


def test_holdout_is_chronological_and_not_a_ros_promotion():
    report=holdout(rows(),{'xpm':1},2025)
    assert report['n']==4 and not report['serving_promoted']
    assert 'not_full_ros' in report['scope']
    current=candidate(rows()[:8],{'xpm':1})
    assert current['status']=='research_candidate' and current['per_game'] is None
    future=rows();future[-1]['values']['fantasy_pat_made']=999
    assert candidate(future[:8],{'xpm':1})==current


def test_exact_kicker_buckets_and_missing_are_not_zero():
    mapping,gaps=weights({'fgm_50p':5,'xpm':1})
    assert mapping['fantasy_fg_60_plus']==5 and not gaps
    assert candidate(rows(),{'xpm':1,'fgmiss':-1})['status']=='insufficient_kicking_evidence'
    assert candidate(rows(),{'xpm':1,'fgm_yds':.1})['missing_scoring_keys']==['fgm_yds']


def test_duplicate_outcomes_cannot_leak_into_holdout():
    import pytest
    with pytest.raises(ValueError,match='duplicate'):
        holdout(rows()+rows()[:1],{'xpm':1},2025)
