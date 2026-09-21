from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from src.ingest.nba_results import participants
from src.ingest.runs import record_run
from src.ingest.espn import sync_scoreboard
from src.ingest.ncaaf_results import sync_ncaaf_results
from src.models.facts import Game


def block(labels, values):
    return {'labels': labels, 'athletes': [{'athlete': {'id': '1', 'displayName': 'Test Player'},
        'didNotPlay': False, 'stats': values}]}


def test_nba_split_blocks_merge_before_combos():
    payload = {'boxscore': {'players': [{'statistics': [
        block(['PTS'], ['10']), block(['REB', 'AST'], ['4', '5']),
        block(['3PT'], ['2-5']), block(['PTS'], ['10'])]}]}}
    rows = list(participants(payload))
    assert len(rows) == 1
    assert rows[0][2]['points_rebounds_assists'] == 19
    assert rows[0][2]['three_pointers_made'] == 2


def test_nba_conflicting_blocks_fail_closed():
    with pytest.raises(ValueError, match='Conflicting NBA stat'):
        list(participants({'boxscore': {'players': [{'statistics': [
            block(['PTS'], ['10']), block(['PTS'], ['11'])]}]}}))


@pytest.mark.parametrize('source', ['', 'nba_box_'+'1'*25, 'mlb_box_'+'1'*25, 'nhl_box_'+'1'*25])
async def test_source_guard_precedes_database_write(source):
    db = AsyncMock()
    with pytest.raises(ValueError, match='1 to 32'):
        async with record_run(db, source):
            pass
    db.flush.assert_not_called()


async def test_source_boundary_is_valid(db):
    async with record_run(db, 'nba_box_'+'1'*24) as run:
        assert len(run.source) == 32


async def test_scoreboard_window_covers_previous_utc_day(db, monkeypatch):
    import src.ingest.espn as module
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 5, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(module, 'datetime', Clock)
    requested=[]
    async def get(self, url, **kwargs):
        requested.append(kwargs['params']['dates'])
        assert kwargs['params'] == {'dates': requested[-1], 'limit': '1000', 'groups': '80'}
        return httpx.Response(200, json={'events': []}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    assert await sync_scoreboard(db, sport='ncaaf') == 0
    assert requested==[f'202609{d:02}' for d in range(4,13)]


async def test_ncaaf_empty_and_unfinished_boxscores_are_retried(db, monkeypatch):
    db.add(Game(sport='ncaaf', season=2026, status='final', espn_event_id='123',
                game_time=datetime.now(timezone.utc)))
    await db.commit()
    async def get(self, url, **kwargs):
        return httpx.Response(200, json={'header': {'competitions': [{'id': '123',
            'status': {'type': {'completed': False}}}]}}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    assert (await sync_ncaaf_results(db))['deferred'] == 1
    assert (await sync_ncaaf_results(db))['games'] == 0  # durable retry cooldown


async def test_ncaaf_completed_results_and_canonical_backfill(db, monkeypatch, tmp_path):
    from config.settings import get_settings
    monkeypatch.setattr(get_settings(),'raw_archive_dir',str(tmp_path))
    from src.ingest.ncaaf_players import _upsert_player
    from src.models.facts import PlayerGameStat
    from sqlalchemy import select
    from scripts.backfill_ncaaf_interceptions import backfill
    await _upsert_player(db, {'id': '1', 'fullName': 'Test Player'})
    game = Game(sport='ncaaf', season=2026, status='final', espn_event_id='123',
                game_time=datetime.now(timezone.utc))
    db.add(game)
    await db.commit()
    category = {'name': 'passing', 'keys': ['passingYards', 'interceptions'],
                'athletes': [{'athlete': {'id': '1', 'displayName': 'Test Player'}, 'stats': ['200', '1']}]}
    async def get(self, url, **kwargs):
        return httpx.Response(200, json={'header': {'competitions': [{'id': '123',
            'status': {'type': {'completed': True}}}]}, 'boxscore': {'players': [
                {'statistics': [category]}, {'statistics': [category]}]}}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    assert (await sync_ncaaf_results(db))['rows_written'] == 2
    assert (await sync_ncaaf_results(db))['games'] == 0
    stat = await db.scalar(select(PlayerGameStat).where(PlayerGameStat.stat_type == 'passing_interceptions'))
    db.add(PlayerGameStat(player_id=stat.player_id, game_id=stat.game_id, stat_type='ints_thrown', value=1))
    await db.commit()
    assert await backfill(db) == 0  # canonical value is never overwritten
    from sqlalchemy import delete
    await db.execute(delete(PlayerGameStat).where(PlayerGameStat.id == stat.id))
    await db.commit()
    assert await backfill(db) == 1
    assert await backfill(db) == 0
