from types import SimpleNamespace
from datetime import datetime, timezone
import httpx
import pytest
from sqlalchemy import select, func
from src.ingest.nhl_results import ice_seconds, participants, sync_nhl_results
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player
from src.services.model_review import review


def test_ice_time_and_unused_goalie():
    assert ice_seconds('17:02') == 1022
    assert ice_seconds('1:60') is None
    assert ice_seconds(None) is None
    payload = {'playerByGameStats': {'homeTeam': {'goalies': [
        {'playerId': 1, 'toi': '00:00', 'saves': 0},
        {'playerId': 2, 'toi': '60:00', 'saves': 22, 'goalsAgainst': 0}]}}}
    assert list(participants(payload)) == [('2', {'time_on_ice_seconds': 3600., 'saves': 22., 'goals_against': 0.})]


def prediction(i, p, y=1):
    return SimpleNamespace(game_id=i, market='spread', probability=p, outcome=y)


def test_review_does_not_promote_without_prospective_and_market_evidence():
    result = review([prediction(i, .8) for i in range(220)],
                    [prediction(i, .5) for i in range(220)])
    assert result['brier_delta_interval_95'][1] < 0
    assert result['promotion_eligible'] is False
    assert 'market_benchmark_missing' in result['blockers']
    assert 'prospective_validation_pending' in result['blockers']


def test_review_rejects_mismatched_events_and_duplicate_games():
    with pytest.raises(ValueError):
        review([prediction(1, .7)], [prediction(2, .5)])
    with pytest.raises(ValueError):
        review([prediction(1, .7), prediction(1, .7)], [prediction(1, .5)])


def test_review_blocks_worse_candidate_and_small_samples():
    result = review([prediction(1, .1)], [prediction(1, .8)])
    assert 'both_scores_must_improve' in result['blockers']
    assert 'fewer_than_200_independent_games' in result['blockers']


async def test_nhl_ingests_full_identity_and_restarts_without_duplicates(db, monkeypatch, tmp_path):
    monkeypatch.setattr('src.scheduler.calibration.get_settings',
                        lambda: SimpleNamespace(raw_archive_dir=str(tmp_path)))
    game = Game(sport='nhl', season=2025, nhl_game_id='123', status='final',
                game_time=datetime(2025, 9, 1, tzinfo=timezone.utc))
    db.add(game)
    await db.commit()
    group = {'forwards': [{'playerId': 1, 'toi': '17:02', 'goals': 1, 'assists': 0}],
             'defense': [{'playerId': 2, 'toi': '00:00'}],
             'goalies': [{'playerId': 3, 'toi': '00:00'}]}
    payload = {'id': 123, 'gameState': 'OFF', 'playerByGameStats': {
        'homeTeam': group, 'awayTeam': {**group, 'forwards': [{'playerId': 4, 'toi': '10:00', 'sog': 2}]}}}
    calls = []
    async def get(self, url):
        calls.append(url)
        external = url.split('/')[-2]
        response = payload if '/boxscore' in url else {'playerId': int(external),
            'firstName': {'default': 'Full'}, 'lastName': {'default': 'Name'+external}, 'position': 'C'}
        return httpx.Response(200, json=response, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    assert (await sync_nhl_results(db))['rows_written'] == 5
    assert (await sync_nhl_results(db))['games'] == 0
    assert len(calls) == 3
    assert await db.scalar(select(func.count()).select_from(Player)) == 2
    assert await db.scalar(select(func.count()).select_from(PlayerGameStat)) == 5
    from src.models.governance import ResultCorrection
    from datetime import timedelta
    group['forwards'][0]['goals'] = 2
    result = await sync_nhl_results(db, game_ids=[game.id], refresh=True)
    assert result['corrections_pending'] == 1
    correction = await db.scalar(select(ResultCorrection))
    correction.first_seen_at -= timedelta(hours=1)
    await db.commit()
    result = await sync_nhl_results(db, game_ids=[game.id], refresh=True)
    assert result['corrections_applied'] == 1
