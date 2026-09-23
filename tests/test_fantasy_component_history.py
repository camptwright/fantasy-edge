from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS
from src.services.fantasy_component_history import total, bound_rows, distributions
from src.services.fantasy_score_history import scoring_hash

NOW=datetime(2026,9,22,tzinfo=timezone.utc)
SCORING={'xpm':1.,'fgm_40_49':3.}


def test_sparse_components_require_played_game_and_known_contract():
    row={'stats':{'gp':1,'xpm':2}}
    assert total(row,SCORING)==2
    assert total(row,{'unknown':1}) is None
    assert total({'stats':{'xpm':2}},SCORING) is None
    assert total({'stats':{'gp':1,'xpm':None}},SCORING) is None


def test_binding_rejects_wrong_period_opponent_and_conflicting_duplicate():
    game=NS(id='g',home_team_id='h',away_team_id='a',game_time=NOW-timedelta(days=10))
    row={'category':'stat','season':'2026','week':1,'sport':'nfl','season_type':'regular',
        'player_id':'p','stats':{'gp':1,'xpm':2},'team':'H','opponent':'A',
        'date':game.game_time.date().isoformat(),'player':{'position':'K'}}
    args=(2026,1,[game],{'H':'h','A':'a'})
    assert list(bound_rows([row],*args))==['p']
    assert not bound_rows([{**row,'week':2}],*args)
    assert not bound_rows([{**row,'opponent':'H'}],*args)
    assert not bound_rows([row,{**row,'stats':{'gp':1,'xpm':3}}],*args)


def fixtures():
    def archive(year,week):
        return NS(synced_at=NOW,kind='actual_components_'+str(year),payload={
            'schema_version':1,'season':year,'week':week,'players':{
                str(p):{'game_id':f'{year}-{week}-{p}','kickoff':(NOW-timedelta(days=30)).isoformat(),
                    'position':'K','stats':{'gp':1,'xpm':2}} for p in range(8)}})
    archives=[archive(2025,w) for w in range(1,10)]+[archive(2026,1)]
    official=[NS(kind='scored_history',week=1,synced_at=NOW,payload={
        'season':'2026','scoring_hash':scoring_hash(SCORING),'points':{str(p):2 for p in range(8)}})]
    return archives,official


def test_exact_scoring_reconciliation_and_minimum_history():
    archives,official=fixtures()
    r=distributions(archives,official,SCORING,2026,3,NOW)['0']
    assert r['status']=='estimated_distribution' and len(r['score_samples'])==10
    official[0].payload['points']['1']=3
    r=distributions(archives,official,SCORING,2026,3,NOW)['0']
    assert r['score_samples']==[] and r['reconciliation_mismatches']==1


def test_no_future_wrong_rules_or_duplicate_game_inflation():
    archives,official=fixtures()
    archives+=archives
    r=distributions(archives,official,SCORING,2026,3,NOW)['0']
    assert r['games']==10
    assert r['reconciliation_samples']==8
    assert not distributions(archives,official,SCORING,2026,3,NOW-timedelta(seconds=1))
    assert distributions(archives,official,{'xpm':2},2026,3,NOW)['0']['score_samples']==[]
