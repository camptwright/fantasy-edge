from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as N
from src.services.fantasy_decision_models import input_deadline


def test_daily_metadata_does_not_expire_hourly_decisions():
    now=datetime(2026,10,10,tzinfo=timezone.utc)
    meta=N(synced_at=now-timedelta(hours=20)); fresh=N(synced_at=now)
    assert input_deadline(meta,fresh,fresh,[fresh],'sleeper',now)==now+timedelta(hours=6)
    assert input_deadline(meta,fresh,fresh,[fresh],'espn',now)<now
    stale=N(synced_at=now-timedelta(hours=7))
    assert input_deadline(meta,stale,fresh,[fresh],'sleeper',now)<now
    assert input_deadline(meta,fresh,fresh,[stale],'sleeper',now)<now


def test_future_metadata_is_not_fresh_and_grace_is_bounded():
    now=datetime(2026,10,10,tzinfo=timezone.utc); fresh=N(synced_at=now)
    assert input_deadline(N(synced_at=now+timedelta(seconds=1)),fresh,fresh,[],'sleeper',now) is None
    assert input_deadline(N(synced_at=now-timedelta(hours=27)),fresh,fresh,[],'sleeper',now)<now
