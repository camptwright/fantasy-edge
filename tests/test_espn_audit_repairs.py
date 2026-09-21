from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from src.ingest.espn import scoreboard_dates,_apply_scores


def test_ranges_expand_to_single_dates_and_validate():
    assert scoreboard_dates(dates='20260920-20260922')==['20260920','20260921','20260922']
    assert scoreboard_dates(dates='20260920')==['20260920']
    for invalid in ('20260922-20260920','20260230','2026','20260920-20260921-20260922'):
        with pytest.raises(ValueError):scoreboard_dates(dates=invalid)


@pytest.mark.parametrize('status,expected',[('scheduled',None),('in_progress',0),('final',0)])
def test_placeholder_scores_not_confused_with_live_shutouts(status,expected):
    game=SimpleNamespace(status=status,home_score=7,away_score=14)
    _apply_scores(game,'0','0',True,False)
    assert game.home_score==expected and game.away_score==14


@pytest.mark.asyncio
async def test_single_date_fetch_deduplicates_repeated_week_events(monkeypatch):
    import src.ingest.espn as module
    run=SimpleNamespace(rows_written=0)
    @asynccontextmanager
    async def record(*args):yield run
    monkeypatch.setattr(module,'record_run',record)
    calls=[]
    async def get(self,url,**kwargs):
        calls.append(kwargs['params']['dates'])
        return httpx.Response(200,json={'events':[{'id':'e'}]},request=httpx.Request('GET',url))
    monkeypatch.setattr(httpx.AsyncClient,'get',get)
    upsert=AsyncMock(return_value=None);monkeypatch.setattr(module,'_upsert_event',upsert)
    assert await module.sync_scoreboard(AsyncMock(),dates='20260920-20260922')==0
    assert len(calls)==3 and all('-' not in d for d in calls)
    assert upsert.await_count==1


def test_sport_failure_isolated_across_two_task_event_loops(monkeypatch):
    import src.scheduler.tasks as module
    calls=[];sessions=[]
    @asynccontextmanager
    async def db():
        session=object();sessions.append(session);yield session
    async def sync(session,sport):
        calls.append(sport)
        if sport=='nfl':raise RuntimeError('fixture failure')
        return 2
    monkeypatch.setattr(module,'get_worker_db',db)
    monkeypatch.setattr(module,'get_settings',lambda:SimpleNamespace(espn_sports=['nfl','ncaaf','nba']))
    monkeypatch.setattr(module,'sync_scoreboard',sync)
    for _ in range(2):
        result=module.sync_espn()
        assert result['rows_written']=={'ncaaf':2,'nba':2}
        assert result['failures']=={'nfl':'RuntimeError'}
    assert calls==['nfl','ncaaf','nba']*2 and len({id(s) for s in sessions})==6


def test_notification_size_is_bounded_in_utf8():
    from src.utils.alerts import bounded_message
    value=bounded_message('⚠ '*5000)
    assert len(value)<=3500 and 'Truncated' in value.decode('utf-8')


def test_health_task_surfaces_delivery_failure(monkeypatch):
    import src.scheduler.tasks as module
    @asynccontextmanager
    async def db():yield object()
    monkeypatch.setattr(module,'get_worker_db',db)
    monkeypatch.setattr(module,'run_health_checks',AsyncMock(return_value=[SimpleNamespace(check='espn_nfl',detail='failed')]))
    monkeypatch.setattr(module,'notify',AsyncMock(return_value=False))
    with pytest.raises(RuntimeError,match='delivery failed'):module.check_data_health()
    monkeypatch.setattr(module,'notify',AsyncMock(return_value=True))
    assert module.check_data_health()=={'issues':1}
