import json
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from src.services.event_weather import binding,context,prioritize


def test_capture_rotates_without_growing_request_budget(tmp_path):
    now=datetime.now(timezone.utc)
    games=[SimpleNamespace(id=str(i),game_time=now+timedelta(hours=i)) for i in range(12)]
    for g in games[:8]:
        directory=tmp_path/'games'/g.id;directory.mkdir(parents=True)
        (directory/'20260916.json').write_text('{}')
    selected=prioritize(games,tmp_path)[:8]
    assert {g.id for g in games[8:]}<={g.id for g in selected}
    assert len(selected)==8


def test_exact_event_binding_does_not_infer_home_venue():
    game=SimpleNamespace(sport='mlb',mlb_game_pk='123')
    payload={'dates':[{'games':[{'gamePk':123,'venue':{'id':9,'name':'Neutral Park',
        'location':{'defaultCoordinates':{'latitude':40,'longitude':-70}},'fieldInfo':{'roofType':'Retractable'}}}]}]}
    result=binding(payload,game)
    assert result['status']=='source_bound_coordinates' and result['roof']=='retractable_unknown'
    game.mlb_game_pk='456'
    assert binding(payload,game)['status']=='event_identity_mismatch'
    football=SimpleNamespace(sport='nfl',espn_event_id='123')
    assert binding({'header':{'id':'123'},'gameInfo':{'venue':{'id':'9','fullName':'Neutral Park'}}},football)['status']=='venue_bound_coordinates_missing'


def test_provider_reschedule_blocks_old_kickoff_binding():
    now=datetime.now(timezone.utc)
    game=SimpleNamespace(sport='mlb',mlb_game_pk='1',game_time=now)
    payload={'dates':[{'games':[{'gamePk':1,'gameDate':(now+timedelta(hours=1)).isoformat(),'venue':{}}]}]}
    assert binding(payload,game)['status']=='provider_kickoff_mismatch'


def test_context_uses_only_prior_archives_and_blocks_changed_kickoff(tmp_path):
    now=datetime(2026,9,15,12,tzinfo=timezone.utc)
    game=SimpleNamespace(id='g',game_time=now+timedelta(hours=1))
    directory=tmp_path/'event-weather'/'games'/'g';directory.mkdir(parents=True)
    row={'id':'proof','captured_at':(now-timedelta(minutes=5)).isoformat(),
         'kickoff':game.game_time.isoformat(),'status':'venue_bound_coordinates_missing'}
    (directory/'a.json').write_text(json.dumps(row))
    future={**row,'id':'future','captured_at':(now+timedelta(minutes=1)).isoformat()}
    (directory/'b.json').write_text(json.dumps(future))
    assert context(game,now,tmp_path)['archive_id']=='proof'
    game.game_time+=timedelta(hours=1)
    assert context(game,now,tmp_path)['status']=='kickoff_changed_or_unknown'
