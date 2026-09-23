from src.services.fantasy_simulation import evaluate
from src.services.fantasy_views import player_view


def player(pid, points, samples, mine=True):
    return dict(player_id=pid,name=pid,position='QB',weekly_points=points,
        score_samples=samples,is_mine=mine,locked=False,injury_status=None,
        weekly_evidence={'status':'pregame_provider_projection'})


def test_underdog_variance_and_reproducibility():
    players=[player('safe',10,[10]*10),player('swing',9,[0,18]*5),player('other',15,[15]*10,False)]
    result=evaluate(players,['safe'],['other'],['QB'])
    assert result==evaluate(players,['safe'],['other'],['QB'])
    assert result['candidate']['player_ids']==['swing']
    assert result['candidate']['expected_points']<result['current']['expected_points']
    assert result['estimated_win_probability_delta']>.4
    assert result['win_probability'] is None and not result['validated']
    assert result['independent_reporting_draws']==result['selection_draws']==4000
    assert result['current']['monte_carlo_standard_error']>=0


def test_missing_locked_injured_and_duplicate_fail_closed():
    a,b=player('a',10,[8,12]*5),player('b',10,[8,12]*5,False)
    assert evaluate([a,b],['a'],['a'],['QB'])['status']=='withheld'
    for key,value in [('locked',True),('injury_status','Questionable'),('score_samples',[1])]:
        assert evaluate([{**a,key:value},b],['a'],['b'],['QB'])['status']=='withheld'


def test_unknown_view_never_becomes_zero():
    row=player_view({'player_id':'p','decision_points':None,'decision_tier':'ranked_only'})
    assert row['projected_points'] is None and row['custom_projected_points'] is None


def test_explicit_specialist_default_is_disclosed_not_fake_history():
    a=player('a',10,[]);b=player('b',10,[8,12]*5,False)
    for p in (a,b):p['position']='K'
    a['distribution_evidence']={'status':'assumed_position_prior',
        'recipe':'explicit_specialist_default_v1','standard_deviation':5.0}
    result=evaluate([a,b],['a'],['b'],['K'])
    assert result['status']=='estimated_research' and not result['validated']
    assert result['assumed_specialist_distributions'][0]['player_id']=='a'
    assert not a['score_samples']
    a['injury_status']='Out'
    assert evaluate([a,b],['a'],['b'],['K'])['status']=='withheld'
