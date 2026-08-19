"""FastAPI app entrypoint. `Dockerfile`'s CMD points uvicorn at
`src.api.main:app`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routers import fantasy, games, health, odds, parlays, props, rankings, signals
from src.api.v1 import router as sports_v1_router
from src.data.cache.db_client import dispose_api_engine
from src.data.cache.redis_client import close_redis
from src.utils.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    yield
    # Pooled engine/connections belong to THIS process's lifetime (constraint
    # #1's API side) - dispose them on shutdown rather than leaking sockets
    # across a container restart-in-place (e.g. during a `docker compose
    # restart` that doesn't recreate the container).
    await dispose_api_engine()
    await close_redis()


app = FastAPI(title="Fantasy Edge API", lifespan=lifespan)

app.include_router(health.router)
app.include_router(games.router)
app.include_router(odds.router)
app.include_router(signals.router)
app.include_router(props.router)
app.include_router(parlays.router)
app.include_router(fantasy.router)
app.include_router(rankings.router)
app.include_router(sports_v1_router)
