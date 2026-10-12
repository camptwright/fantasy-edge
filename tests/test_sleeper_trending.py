from datetime import datetime, timedelta, timezone

from src.services import sleeper_trending as st


async def test_refresh_is_throttled_and_latest_expires(db):
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    calls = []

    async def fetcher():
        calls.append(1)
        return {"4866": 5400}

    assert (await st.refresh(db, now=now, fetcher=fetcher))["status"] == "refreshed"
    assert (await st.refresh(db, now=now + timedelta(minutes=30), fetcher=fetcher))["status"] == "fresh"
    assert len(calls) == 1
    assert (await st.latest(db, now=now + timedelta(hours=1)))["players"] == {"4866": 5400}
    assert await st.latest(db, now=now + timedelta(hours=7)) is None  # stale crowd data is not shown
