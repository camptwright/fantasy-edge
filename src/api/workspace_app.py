"""Isolated replacement read service: no scheduler, mutations, or provider calls.

The existing API also mounts these v2 routes for eventual cutover. This preview
process uses a small, database-enforced read-only pool and bounded statements.
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from config.settings import get_settings
from src.api.auth import require_fantasy_token
from src.api.routers.workspace import router
from src.db.client import get_db
from src.api.performance import PerformanceMiddleware, snapshot


@asynccontextmanager
async def lifespan(app):
    engine = create_async_engine(get_settings().database_url, pool_size=2,
        max_overflow=0, pool_timeout=2, pool_pre_ping=True,
        connect_args={'timeout': 2, 'server_settings': {'default_transaction_read_only': 'on',
                                         'application_name': 'fantasy-workspace-preview',
                                         'statement_timeout': '2000'}})
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def read_db():
        try:
            async with factory() as db:
                yield db
        except (OSError, TimeoutError):
            from fastapi import HTTPException
            raise HTTPException(503, 'Preview database connection unavailable',
                                headers={'Cache-Control': 'no-store', 'Retry-After': '2'}) from None

    app.dependency_overrides[get_db] = read_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


app = FastAPI(title='Fantasy Edge workspace preview', lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router, dependencies=[Depends(require_fantasy_token)])
app.add_middleware(PerformanceMiddleware)


async def database_unavailable(request, exc):
    # Never expose SQL, connection strings or driver diagnostics to the client.
    return JSONResponse({'detail': 'Preview database unavailable or busy; retry shortly'},
                        status_code=503, headers={'Cache-Control': 'no-store', 'Retry-After': '2'})


app.add_exception_handler(DBAPIError, database_unavailable)
app.add_exception_handler(PoolTimeout, database_unavailable)


@app.get('/health/ready', dependencies=[Depends(require_fantasy_token)])
async def ready(response: Response, db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    await db.execute(text('SELECT 1'))
    return {'status': 'ready', 'service': 'workspace-preview'}


@app.get('/api/v2/operations/runtime', dependencies=[Depends(require_fantasy_token)])
async def runtime_history(response: Response, db=Depends(get_db)):
    from src.services.runtime_history import status
    response.headers['Cache-Control'] = 'no-store'
    return await status(db)


@app.get('/operations/performance', dependencies=[Depends(require_fantasy_token)])
async def performance(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return {**snapshot(), 'service': 'workspace-preview',
            'limitations': 'Process-local backend timings, not browser navigation or worker/database health.'}


@app.get('/api/v2/operations/release',dependencies=[Depends(require_fantasy_token)])
async def release(response:Response):
    from asyncio import to_thread
    from src.services.release_manifest import status
    response.headers['Cache-Control']='no-store'
    return await to_thread(status)
