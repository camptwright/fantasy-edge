from src.services.fantasy_evidence_counts import provider_counts
from src.services.fantasy_evidence_counts import lineup_counts
from src.services.fantasy_evidence_counts import result_backlog


def test_result_backlog_deduplicates_versions_and_leagues_not_players():
    records=[dict(id=i,player_id=p,game_id='g') for i,p in [('a','p'),('b','p'),('c','q')]]
    grades=[dict(id=i,status='missing_scoring_results',result_blocker='missing_player_results',missing=['yards']) for i in ('a','b','c')]
    result=result_backlog(records,grades)
    assert result['blocked_captures']==3 and result['unique_player_games']==2
    assert result['unique_games']==1 and result['additional_captures']==1
    assert result['player_games_by_missing_category']=={'yards':2}
    assert result['player_games_by_blocker']=={'missing_player_results':2}
    assert result_backlog([],[])['blocked_captures']==0


def test_legacy_missing_reason_is_not_reinterpreted_as_nonparticipation():
    result=result_backlog([dict(id='a',player_id='p',game_id='g')],
                          [dict(id='a',status='missing_scoring_results',missing=[])])
    assert result['player_games_by_blocker']=={'unclassified_legacy_result':1}


def test_lineup_counts_keep_old_evidence_separate_and_report_inner_failure():
    base={'league_id':'L','week':3,'lineups':{'games':[{'id':'g'}]},'lineup_experiment':{'frozen':True}}
    records=[{**base,'id':'old','version':'v1'},{**base,'id':'new','version':'v2'},
             {**base,'id':'pending','version':'v2','week':4,'lineups':{'games':[{'id':'next'}]}}]
    grades=[{'id':'old','status':'graded','lineup_experiment':{'status':'graded'}},
            {'id':'new','status':'graded','lineup_experiment':{'status':'missing_player_points'}},
            {'id':'pending','status':'awaiting_final'}]
    result=lineup_counts(records,grades,'v2')
    assert result['current_version_counts']=={'missing_player_points':1,'awaiting_final':1}
    assert result['counts']['graded']==1
    assert result['unique_matchup_slates']==2 and result['unique_graded_matchup_slates']==1


def test_versions_are_not_new_observations():
    records=[dict(id='a',league_id='L',player_id='p',game_id='g',recipe='v1'),
             dict(id='b',league_id='L',player_id='p',game_id='g',recipe='v2'),
             dict(id='c',league_id='L',player_id='q',game_id='g',recipe='v2')]
    result=provider_counts(records,[{'id':'a','status':'graded_platform_total'},
                                   {'id':'b','status':'graded_platform_total'}])
    assert result['captures']==3
    assert result['unique_league_player_games']==2
    assert result['unique_graded_league_player_games']==1
    assert result['additional_versioned_captures']==1
    assert result['captures_by_recipe']=={'v1':1,'v2':2}
    assert provider_counts([],[])['unique_graded_league_player_games']==0
