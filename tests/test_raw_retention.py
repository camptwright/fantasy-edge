from datetime import datetime,timezone,timedelta
from types import SimpleNamespace as NS
from src.services.raw_retention import eligible


def test_retention_requires_durable_final_success_and_preserves_corrections():
    now=datetime.now(timezone.utc);old=now-timedelta(days=120);cutoff=now-timedelta(days=90)
    state=NS(status='succeeded',last_attempt_at=now);game=NS(status='final',game_time=old)
    payload={'observed_at':old.isoformat(),'payload_hash':'h'}
    assert eligible(payload,state,game,set(),cutoff,True)
    assert not eligible(payload,state,game,{'h'},cutoff,True)
    assert not eligible(payload,state,game,set(),cutoff,False)
    state.status='confirming'
    assert not eligible(payload,state,game,set(),cutoff,True)
