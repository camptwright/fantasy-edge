from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid
import pytest
from src.services import lab_availability

@pytest.mark.asyncio
@pytest.mark.parametrize('fresh', [True, False])
async def test_event_evidence_records_policy_without_numeric_probability(monkeypatch, fresh):
    now=datetime.now(timezone.utc)
    pid=uuid.uuid4()
    game=SimpleNamespace(id=uuid.uuid4(),sport='nfl',espn_event_id='42',game_time=now+timedelta(hours=2))
    event={'observed_at':(now-timedelta(hours=0 if fresh else 2)).isoformat(),
           'event_id':'42','kickoff':game.game_time.isoformat(),'coverage':'reported',
           'rows':[{'athlete_id':'7','reported_at':now.isoformat(),'status':'Out'}]}
    monkeypatch.setattr(lab_availability,'game_snapshots',lambda *args:{str(game.id):event})
    db=AsyncMock()
    db.scalars.return_value=SimpleNamespace(all=lambda:[SimpleNamespace(player_id=pid,external_id='7')])
    result=(await lab_availability.contexts(db,'nfl',[pid],{pid:game},now))[pid]
    assert result['shadow_action']==('abstain' if fresh else 'conditional_only')
    assert result['participation_probability'] is None
    assert result['used_for_numeric_adjustment'] is False

@pytest.mark.asyncio
async def test_no_game_is_explicit(monkeypatch):
    monkeypatch.setattr(lab_availability,'game_snapshots',lambda *args:{})
    result=await lab_availability.contexts(AsyncMock(),'nfl',[],{'p':None},datetime.now(timezone.utc))
    assert result['p']['status']=='no_scheduled_game'
