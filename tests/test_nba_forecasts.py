from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import httpx
from sqlalchemy import select, func
from src.ingest.nba_results import participants, sync_nba_results
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player
from src.services.forecast_capture import eligible, model_digest


def team(external='1', dnp=False):
    return {'statistics': [{'labels': ['MIN', 'PTS', 'REB', 'AST', '3PT'], 'athletes': [{
        'athlete': {'id': external, 'displayName': 'Full Name'+external}, 'didNotPlay': dnp,
        'stats': ['0', '2', '3', '4', '1-3']}]}]}


def test_parser_handles_combo_and_explicit_dnp():
    rows = list(participants({'boxscore': {'players': [team(), team('2', True)]}}))
    assert len(rows) == 1
    stats = rows[0][2]
    assert stats['points_rebounds_assists'] == 9
    assert stats['three_pointers_made'] == 1
    assert stats['minutes'] == 0  # rounded minutes do not override explicit participation
    assert 'turnovers' not in stats


def test_forecast_must_finish_before_game_start():
    now = datetime.now(timezone.utc)
    game = SimpleNamespace(status='scheduled', game_time=now+timedelta(seconds=1))
    assert eligible(game, now)
    assert not eligible(game, now+timedelta(seconds=1))
    game.game_time = None
    assert not eligible(game, now)
    assert len(model_digest()) == 64


async def test_nba_identity_and_result_ingestion_restarts(db, monkeypatch, tmp_path):
    monkeypatch.setattr('src.scheduler.calibration.get_settings',
                        lambda: SimpleNamespace(raw_archive_dir=str(tmp_path)))
    db.add(Game(sport='nba', season=2026, status='final', espn_event_id='123',
                game_time=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    await db.commit()
    payload = {'header': {'competitions': [{'id': '123', 'status': {'type': {'completed': True}}}]},
               'boxscore': {'players': [team(), team('2')]}}
    calls = []
    async def get(self, url, **kwargs):
        calls.append(url)
        return httpx.Response(200, json=payload, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    first = await sync_nba_results(db)
    assert first['rows_written'] == 18
    assert (await sync_nba_results(db))['games'] == 0
    assert len(calls) == 1
    assert await db.scalar(select(func.count()).select_from(Player)) == 2
    assert await db.scalar(select(func.count()).select_from(PlayerGameStat)) == 18


def test_archive_publishes_complete_json_without_temp_files(tmp_path, monkeypatch):
    import json
    import src.scheduler.calibration as module
    monkeypatch.setattr(module, 'get_settings', lambda: SimpleNamespace(raw_archive_dir=str(tmp_path)))
    path = module.archive('forecasts', {'records': []})
    from pathlib import Path
    assert json.loads(Path(path).read_text()) == {'records': []}
    assert not list(tmp_path.rglob('*.tmp'))


async def test_empty_capture_is_valid_and_keeps_explicit_status(db):
    from src.services.forecast_capture import capture
    payload = await capture(db)
    assert payload['records'] == []
    assert payload['model_status'] == 'experimental_user_overrides'
    assert payload['captured_at'] >= payload['started_at']
