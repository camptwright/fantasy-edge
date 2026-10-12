from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N

from src.services.fantasy_score_history import scoring_hash
from src.services.fantasy_specialist_prospective import freeze, grade


def fixture():
    now=datetime(2026,10,9,tzinfo=timezone.utc)
    rules={'fgm':3};contract=scoring_hash(rules)
    league=N(league_id='l',season='2026',platform='sleeper',scoring_settings=rules)
    games=[N(id=f'g{w}',week=w,sport='nfl',season=2026,game_type='REG',
        home_team_id='t',away_team_id='other',status='scheduled',game_time=now+timedelta(days=w)) for w in (5,6)]
    snapshots=[N(league_id='l',kind='scored_history',week=w,synced_at=now,
        payload={'schema_version':1,'season':'2026','week':w,'scoring_hash':contract,
        'scoring_contract':rules,'points':{'k':6}}) for w in (1,2)]
    snapshots.append(N(league_id='l',kind='player_metadata',week=0,synced_at=now,payload={'k':{'position':'K'}}))
    player={'player_id':'k','position':'K','team':'ABC','ros':{'status':'complete_schedule_candidate'},
        'next_games':[{'id':g.id,'week':g.week,'kickoff':g.game_time.isoformat()} for g in games]}
    lab={'status':'candidate','coverage':{},'players':[player],'week':5,'recipe_version':'version'}
    return now,league,games,snapshots,lab,[N(id='t',nflverse_abbr='ABC')]


def test_pregame_frozen_ids_and_unknown_kickoff_not_cleared():
    now,l,g,s,lab,t=fixture()
    records,_=freeze(lab,l,s,g,t,now)
    assert len(records)==3
    assert {r['horizon_games'] for r in records}=={1,2}
    assert all(not r['serving_promoted'] for r in records)
    assert [r['id'] for r in records]==[r['id'] for r in freeze(lab,l,s,g,t,now+timedelta(hours=1))[0]]
    g[1].game_time=None
    remaining,blockers=freeze(lab,l,s,g,t,now)
    assert len(remaining)==1 and blockers['unbound_or_started_game']==1


def test_final_exact_rules_complete_horizon_only():
    now,l,g,s,lab,t=fixture()
    record=freeze(lab,l,s,g,t,now)[0][-1]
    later=now+timedelta(days=10)
    for game in g:
        game.status='final'
        s.append(N(league_id='l',kind='scored_history',week=game.week,synced_at=later,
            payload={'schema_version':1,'season':'2026','week':game.week,
                'scoring_hash':record['scoring_contract'],'scoring_contract':l.scoring_settings,
                'game_ids':[game.id],'points':{'k':0}}))
    result=grade(record,s,g,later)
    assert result['status']=='graded' and result['actual_points']==0
    s[-1].payload['points']={}
    assert grade(record,s,g,later)['status']=='awaiting_complete_horizon'
    s[-1].payload['points']={'k':5};s[-1].payload['scoring_contract']={'fgm':4}
    assert grade(record,s,g,later)['status']=='awaiting_complete_horizon'


def test_metadata_season_rookie_and_future_history_excluded():
    now,l,g,s,lab,t=fixture()
    lab['players'][0]['position']='RB'
    s[-1].payload={'k':{'position':'RB','years_exp':0,'experience_season':'2025'}}
    assert not freeze(lab,l,s,g,t,now)[0]
    s[-1].payload['k']['experience_season']='2026'
    assert freeze(lab,l,s,g,t,now)[0]
    s[0].synced_at=now+timedelta(days=1)
    assert not freeze(lab,l,s,g,t,now)[0]


def test_started_event_and_postgame_capture_rejected():
    now,l,g,s,lab,t=fixture()
    record=freeze(lab,l,s,g,t,now)[0][0]
    record['captured_at']=(now+timedelta(days=7)).isoformat()
    assert grade(record,s,g,now)['status']=='invalid_postgame_capture'
    for game in g:game.status='live'
    assert not freeze(lab,l,s,g,t,now)[0]
