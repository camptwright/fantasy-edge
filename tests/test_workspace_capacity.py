import asyncio
from threading import Event
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from src.services.workspace_capacity import admitted_trade


@pytest.mark.asyncio
async def test_busy_rejected_before_db_and_cancellation_keeps_capacity():
    started, finish = Event(), Event()
    def calculate(data):
        started.set()
        assert finish.wait(3)
        return data
    first = asyncio.create_task(admitted_trade(AsyncMock(return_value=1), calculate))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError): await first
        load = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await admitted_trade(load, lambda x: x)
        assert exc.value.status_code == 429
        assert exc.value.headers['Retry-After'] == '2'
        load.assert_not_awaited()
    finally:
        finish.set()
        # Let the independently shielded thread task complete before loop teardown.
        for _ in range(100):
            try:
                assert await admitted_trade(AsyncMock(return_value=2), lambda x: x) == 2
                break
            except HTTPException:
                await asyncio.sleep(.01)
        else: pytest.fail('Capacity was not released')


@pytest.mark.asyncio
async def test_failures_release_capacity():
    with pytest.raises(ValueError):
        await admitted_trade(AsyncMock(side_effect=ValueError()), lambda x:x)
    def fail(_): raise RuntimeError('calculation failed')
    with pytest.raises(RuntimeError):
        await admitted_trade(AsyncMock(return_value=1), fail)
    assert await admitted_trade(AsyncMock(return_value=3), lambda x:x) == 3


def test_capacity_works_across_distinct_event_loops():
    for _ in range(2):
        assert asyncio.run(admitted_trade(AsyncMock(return_value=4), lambda x:x)) == 4
