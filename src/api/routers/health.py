from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.cache.db_client import get_db
from src.data.cache.redis_client import get_redis

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    db_ok = True
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    redis_ok = True
    try:
        await get_redis().ping()
    except Exception:
        redis_ok = False

    status = "ok" if db_ok and redis_ok else "degraded"
    return {"status": status, "postgres": db_ok, "redis": redis_ok}
