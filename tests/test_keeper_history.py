from copy import deepcopy
import pytest
from src.ingest.keeper_history import validate,player_evidence


def data():
    return ({'league_id':'l','draft_id':'d','season':'2026'},
        {'league_id':'l','draft_id':'d','season':'2026','sport':'nfl','status':'complete'},
        [{'player_id':'p','draft_id':'d','round':6,'roster_id':1,'pick_no':61,'is_keeper':None}])


def test_exact_draft_and_unknown_keeper_flag():
    payload=validate(*data());e=player_evidence(payload,'p',1)
    assert e['draft_round']==6 and e['same_draft_roster']
    assert e['kept_in_draft_season'] is None
    assert not player_evidence(payload,'p',2)['same_draft_roster']
    assert player_evidence(payload,'missing',1)['status']=='missing_or_ambiguous_draft_pick'


@pytest.mark.parametrize('field,value',[('league_id','wrong'),('season','2025'),('status','drafting'),('sport','nba')])
def test_wrong_draft_rejected(field,value):
    league,draft,picks=data();draft[field]=value
    with pytest.raises(ValueError):validate(league,draft,picks)


def test_duplicate_and_boolean_round_rejected():
    league,draft,picks=data()
    with pytest.raises(ValueError):validate(league,draft,picks+deepcopy(picks))
    picks[0]['round']=True
    with pytest.raises(ValueError):validate(league,draft,picks)


def test_collection_accepts_string_archive_path(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, Mock
    from src.ingest.keeper_history import collect
    from src.services.keeper_rules import LEAGUE_ID
    league,draft,picks=data()
    league.update(league_id=LEAGUE_ID,draft_id='123')
    draft.update(league_id=LEAGUE_ID,draft_id='123')
    picks[0]['draft_id']='123'
    responses=[Mock(json=Mock(return_value=value)) for value in (draft,picks)]
    db=Mock(scalar=AsyncMock(return_value=None))
    client=Mock(get=AsyncMock(side_effect=responses))
    snapshot=AsyncMock()
    monkeypatch.setattr('src.ingest.sleeper._snapshot',snapshot)
    monkeypatch.setattr('src.scheduler.calibration.archive',lambda *args:'/tmp/evidence.json')
    assert asyncio.run(collect(db,client,league))['picks']==1
    assert snapshot.call_args.args[-1]['archive']=='evidence.json'
