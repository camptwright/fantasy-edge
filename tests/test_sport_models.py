from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from src.services.sport_distributions import Regression, above, replay
from src.ingest.mlb_results import player_results


def test_regression_fits_scale_bias_and_residuals():
    model = Regression()
    for i in range(200):
        x = i % 20
        model.update(x, 3*x+2+(1 if i % 2 else -1))
    slope, bias, sigma = model.parameters()
    assert slope == pytest.approx(3, abs=.02)
    assert bias == pytest.approx(2, abs=.2)
    assert .9 < sigma < 1.1
    assert Regression().predict(3) is None


def test_probability_has_correct_direction_and_complement():
    assert above(0, 3, 0) == .5
    assert above(2, 3, 1.5) > .5
    assert above(2, 3, -1.5) > above(2, 3, 1.5)
    assert above(0, 3, 1.5)+above(0, 3, -1.5) == pytest.approx(1)


def test_replay_freezes_same_day_inputs(monkeypatch):
    import src.services.sport_distributions as module
    games = [SimpleNamespace(id=i, game_time=datetime(2025, 1, 1, tzinfo=timezone.utc)+timedelta(days=i//2),
        home_team_id='h', away_team_id='a', home_score=5+i%3, away_score=2+i%2) for i in range(130)]
    lines = {g.id: {'spread': -1.5, 'total': 7.5} for g in games}
    calls = []
    def spy(mean, sigma, threshold):
        calls.append((mean, sigma, threshold))
        return above(mean, sigma, threshold)
    monkeypatch.setattr(module, 'above', spy)
    replay(games, lines, 'mlb')
    first = list(calls)
    games[-2].home_score = 50
    calls.clear()
    replay(games, lines, 'mlb')
    assert calls == first


def test_mlb_game_stats_keep_batting_and_pitching_distinct():
    player = {'person': {'id': 1}, 'stats': {
        'batting': {'gamesPlayed': 1, 'hits': 3, 'runs': 2, 'rbi': 1,
                    'doubles': 1, 'triples': 0, 'homeRuns': 1, 'strikeOuts': 2},
        'pitching': {'gamesPlayed': 1, 'strikeOuts': 7, 'outs': 17}}}
    rows = list(player_results({'teams': {'home': {'players': {'ID1': player}}}}))
    values = {stat: value for _, stat, value in rows}
    assert values['batter_strikeouts'] == 2
    assert values['strikeouts'] == 7
    assert values['pitching_outs'] == 17
    assert values['singles'] == 1
    assert values['hits_runs_rbis'] == 6
    assert 'walks_allowed' not in values


def test_mlb_bench_and_season_totals_are_not_outcomes():
    player = {'person': {'id': 1}, 'stats': {'batting': {'gamesPlayed': 0, 'hits': 0}},
              'seasonStats': {'batting': {'gamesPlayed': 120, 'hits': 100}}}
    assert list(player_results({'teams': {'home': {'players': {'ID1': player}}}})) == []


async def test_mlb_ingestion_is_restartable_and_idempotent(db, monkeypatch):
    import httpx
    from sqlalchemy import select, func
    from src.models.facts import Game, PlayerGameStat
    from src.models.identity import Player, PlayerExternalId
    from src.ingest.mlb_results import sync_mlb_results
    player = Player(sport='mlb', full_name='Test Batter')
    db.add(player)
    await db.flush()
    db.add(PlayerExternalId(player_id=player.id, source='mlb_stats_api', external_id='1'))
    db.add(Game(sport='mlb', season=2025, status='final', mlb_game_pk='123',
                game_time=datetime(2025, 1, 1, tzinfo=timezone.utc)))
    await db.commit()
    person = {'person': {'id': 1}, 'stats': {'batting': {'gamesPlayed': 1, 'hits': 2}}}
    payload = {'teams': {'home': {'players': {'ID1': person}},
                         'away': {'players': {'ID2': {'person': {'id': 2}, 'stats': {}}}}}}
    calls = []
    async def get(self, url, **kwargs):
        calls.append(url)
        if url.endswith('/schedule'):
            return httpx.Response(200, json={'dates': [{'games': [{'gamePk': 123,
                'status': {'abstractGameState': 'Final'}}]}]}, request=httpx.Request('GET', url))
        return httpx.Response(200, json=payload, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    assert (await sync_mlb_results(db))['rows_written'] == 1
    assert (await sync_mlb_results(db))['games'] == 0
    assert len(calls) == 2
    assert await db.scalar(select(func.count()).select_from(PlayerGameStat)) == 1
