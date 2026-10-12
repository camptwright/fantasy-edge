from src.services.fantasy_locks import lineup, waivers
from src.services.fantasy_simulation import legal_lineups
from src.services.fantasy_lineup_validation import grade, frozen


def p(pid,pos,points,locked=False):
    return dict(player_id=pid,name=pid,position=pos,decision_points=points,
        weekly_points=points,locked=locked,injury_status=None)


def test_event_hold_excludes_new_starts_but_preserves_locked_slots():
    from src.services.fantasy_simulation import eligibility_reasons
    from src.services.fantasy_values import availability_flag
    held={**p('held','WR',100),'game_availability':{'hold_recommendation':True}}
    safe=p('safe','WR',10)
    assert lineup([held,safe],['WR'],['safe'])['lineup'][0]['player_id']=='safe'
    assert lineup([{**held,'locked':True},safe],['WR'],['held'])['lineup'][0]['player_id']=='held'
    assert 'event_availability_hold' in eligibility_reasons(held)
    assert availability_flag(held)
    assert lineup([{**held,'game_availability':{},'injury_status':' Out '},safe],['WR'],['safe'])['lineup'][0]['player_id']=='safe'


def test_checkpoint_does_not_outlive_event_evidence():
    from datetime import datetime, timezone, timedelta
    from src.services.fantasy_read_model import expires
    now=datetime.now(timezone.utc)
    data={'players':[{'game_availability':{'observed_at':(now-timedelta(minutes=59)).isoformat()}}]}
    assert expires(data,now)==now+timedelta(minutes=1)


def test_locked_starter_cannot_move_even_for_higher_points():
    players=[p('a','WR',None,True),p('b','WR',5),p('c','WR',20),p('d','WR',100,True)]
    result=lineup(players,['WR','FLEX','BN'],['a','b'])
    assert [x['player_id'] for x in result['lineup']]==['a','c']
    assert result['total'] is None and result['unlocked_points']==20
    assert result['lineup'][0]['locked']


def test_unbound_starter_and_duplicate_lineups_fail_closed():
    assert lineup([p('a','WR',10)],['QB'],['a'])['status']=='withheld'
    assert lineup([p('a','WR',10)],['WR','WR'],['a','a'])['status']=='withheld'
    assert lineup([p('a','WR',None,True)],['WR'],['a'])['status']=='all_slots_locked'


def test_waiver_gain_only_changes_unlocked_slots_and_preserves_starters():
    mine=[p('a','WR',None,True),p('b','WR',10),p('c','WR',5)]
    result=waivers(mine,[p('upgrade','WR',20)],['WR','FLEX'],['a','b'])
    move=result['moves'][0]
    assert move['drop_id']=='c' and move['lineup_gain']==10
    assert move['after_total'] is None
    assert move['after_lineup'][0]['player_id']=='a'
    assert not waivers(mine,[p('upgrade','WR',20,True)],['WR','FLEX'],['a','b'])['moves']


def test_legal_search_allows_multi_player_changes_and_caps():
    pool=[p(str(i),'WR',i) for i in range(6)]
    rows,limited=legal_lineups(pool,['WR','FLEX'],limit=100)
    assert len(rows)==15 and not limited
    assert all(len(set(r))==2 for r in rows)
    rows,limited=legal_lineups(pool,['WR','FLEX'],limit=3)
    assert len(rows)==3 and limited


def test_waiver_ties_are_explicit_and_do_not_depend_on_roster_order():
    mine=[p('starter','WR',10),p('z','QB',20),p('a','QB',5)]
    first=waivers(mine,[p('add','WR',20)],['WR'],['starter'])
    second=waivers(list(reversed(mine)),[p('add','WR',20)],['WR'],['starter'])
    assert first==second
    move=first['moves'][0]
    assert move['equivalent_drop_ids']==['a','z']
    assert move['drop_decision_status']=='unresolved_retention_cost'
    assert move['drop_selection']=='stable_id_not_retention_value'
    assert move['lineup_gain']==10


def test_lineup_grading_missing_and_ties():
    record={'lineups':{'opponent_starters':['other']},'lineup_experiment':{'simulation':{
        'current':{'player_ids':['a'],'estimated_win_probability':.7},
        'candidate':{'player_ids':['b'],'estimated_win_probability':.6}}}}
    assert grade(record,{'a':10,'other':5})['status']=='missing_player_points'
    result=grade(record,{'a':10,'b':5,'other':5})
    assert abs(result['current']['brier']-.09)<1e-9
    assert result['candidate']['tied'] and result['candidate']['brier']==.36
    assert frozen({'lineup_simulation':{'status':'withheld'}}) is None


def test_shared_week_draws_keep_observed_comovement():
    from src.services.fantasy_simulation import evaluate
    a,b=p('a','QB',10),p('b','QB',10)
    for player in (a,b):
        player.update(is_mine=player is a,score_samples=[5,15]*4,
            weekly_evidence={'status':'pregame_provider_projection'},
            distribution_evidence={'evidence':[{'week':i,'points':5 if i%2 else 15} for i in range(1,9)]})
    result=evaluate([a,b],['a'],['b'],['QB'])
    assert result['sampling_method']=='joint_platform_week_residuals'
    assert result['current']['estimated_tie_probability']==1


def test_espn_overrides_change_scoring_fingerprint():
    from src.services.fantasy_score_history import scoring_hash
    assert scoring_hash({'x':1},{'pointsOverrides':{'16':2}})!=scoring_hash({'x':1},{'pointsOverrides':{'16':3}})


def test_espn_starters_and_slots_share_canonical_order():
    from src.ingest.espn_fantasy import _expand_roster_positions,_parse_roster_entries
    payload={'settings':{'rosterSettings':{'lineupSlotCounts':{'23':1,'4':1,'0':1}}}}
    assert _expand_roster_positions(payload)==['QB','WR','FLEX']
    team={'roster':{'entries':[{'lineupSlotId':slot,'playerPoolEntry':{'player':{'id':pid}}}
        for slot,pid in [(23,3),(4,2),(0,1)]]}}
    assert _parse_roster_entries(team,{}, {},3)[0]==['1','2','3']
