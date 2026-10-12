"""Per-process, non-queuing research admission control; no event-loop-bound locks."""
import asyncio
from threading import BoundedSemaphore

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

trade_slots = BoundedSemaphore(1)


async def admitted_trade(load, calculate):
    # Reject before touching the database, leaving overview requests independent.
    if not trade_slots.acquire(blocking=False):
        raise HTTPException(429, 'Trade research is busy; retry shortly',
                            headers={'Retry-After': '2', 'Cache-Control': 'no-store'})
    dispatched = False
    try:
        data = await load()
        def worker():
            try:
                return calculate(data)
            finally:
                trade_slots.release()
        task = asyncio.create_task(run_in_threadpool(worker))
        dispatched = True
        # A disconnected caller must not free capacity while its CPU work runs.
        task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        return await asyncio.shield(task)
    finally:
        if not dispatched:
            trade_slots.release()
