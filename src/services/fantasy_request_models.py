"""API-only single-flight generation; no cached decisions across requests.

Generation owns its session so a disconnected caller cannot close the session
used by another caller. Worker tasks continue to use the uncached build().
"""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from fastapi import HTTPException
from sqlalchemy import text


class ModelRequests:
    def __init__(self, capacity=8):
        self.capacity = capacity
        self.pending = {}
        self.gate = asyncio.Semaphore(1)

    async def get(self, key, generate):
        task = self.pending.get(key)
        if task is None:
            if len(self.pending) >= self.capacity:
                raise HTTPException(503, 'Fantasy calculation capacity reached; retry shortly',
                                    headers={'Retry-After': '5'})

            async def run():
                async with self.gate:
                    return await generate()

            task = asyncio.create_task(run())
            self.pending[key] = task

            def finished(done):
                if self.pending.get(key) is done:
                    self.pending.pop(key, None)
                if not done.cancelled():
                    done.exception()  # Consume failures even if all callers disconnected.

            task.add_done_callback(finished)
        try:
            result = await asyncio.wait_for(asyncio.shield(task), timeout=25)
        except TimeoutError:
            raise HTTPException(503, 'Fantasy calculation still running; retry shortly',
                                headers={'Retry-After': '5'}) from None
        # Value adapters may mutate their inputs. Never share mutable decisions.
        return deepcopy(result)


requests = ModelRequests()


async def build(_request_db, league_id, **options):
    from src.db.client import get_db
    from src.services.fantasy_decision_models import build as generate
    normalized = {**options}
    if 'selected_player_ids' in normalized:
        normalized['selected_player_ids'] = tuple(sorted(set(map(str, normalized['selected_player_ids']))))
    key = (league_id, tuple(sorted(normalized.items())))

    async def run():
        from src.api.performance import record_fantasy_read
        async with asynccontextmanager(get_db)() as db:
            # Bind every input to one snapshot, including cache validation and
            # a fallback build. Ingestion must not mix roster/scoring versions
            # across the generator's multiple SELECTs. This session is ours.
            await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            if not normalized:
                from src.services.fantasy_read_model import read
                cached=await read(db,league_id)
                if cached is not None:
                    record_fantasy_read('checkpoint_hit')
                    return cached
                record_fantasy_read('checkpoint_miss')
            else:
                record_fantasy_read('custom_request')
            try:
                result=await generate(db, league_id, **normalized)
            except Exception:
                record_fantasy_read('generation_failed')
                raise
            record_fantasy_read('generated')
            return result

    return await requests.get(key, run)
