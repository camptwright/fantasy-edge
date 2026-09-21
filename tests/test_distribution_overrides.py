from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from src.services.quote_eligibility import confirm_quote
from src.services import serving_distributions as serving
from src.services.ncaaf_candidate_training import fit, replay
from src.services.forecast_capture import model_digest
from src.services.elo import implied_margin, spread_cover_probability
from src.services.projections import over_probability
from src.api.routers.sportsbook import signal_rows, prop_rows
from src.ingest.identity import resolve_team
from src.models.facts import Game, TeamMarketLine, PlayerPropLine, PlayerGameStat
from src.models.identity import Player
from src.models.ratings import TeamRating


def test_pinned_scope_sign_and_rollback(monkeypatch):
    report, digest = serving.artifact()
    assert len(digest) == 64
    assert serving.distribution_status()['player_prop_stats'] == ['fg_made', 'kicking_points',
        'pass_rush_yards', 'passing_yards', 'receiving_touchdowns', 'receptions',
        'rushing_attempts', 'rushing_touchdowns', 'xp_made']
    assert report['spread']['parameters']['slope'] == 5.662019040308
    assert report['player_props']['receptions']['parameters']['bias_stddev'] == 0.19160393936719683
    p, candidate = serving.spread_probability(3, -7, .25, 'ncaaf', True)
    easier, _ = serving.spread_probability(3, 7, .25, 'ncaaf', True)
    assert 0 < p < easier < 1 and candidate
    assert serving.spread_probability(3, -7, .25, 'nfl', True) == (.25, None)
    assert serving.spread_probability(3, -7, .25, 'ncaaf', False) == (.25, None)
    assert serving.prop_parameters(5, 2, 'ncaaf', 'fantasy_points', True) == (5, 2, None)
    assert serving.prop_parameters(5, 2, 'nfl', 'receptions', True) == (5, 2, None)
    before = model_digest()
    monkeypatch.setattr(serving, 'get_settings', lambda: SimpleNamespace(
        ncaaf_spread_calibration_enabled=False, ncaaf_prop_calibration_enabled=False))
    assert serving.spread_probability(3, -7, .25, 'ncaaf', True) == (.25, None)
    assert serving.prop_parameters(5, 2, 'ncaaf', 'receptions', True) == (5, 2, None)
    assert model_digest() != before


@pytest.mark.parametrize('stat', ['fg_made', 'xp_made', 'kicking_points'])
def test_v3_kicking_preserves_mean_evidence_scope_and_rollback(stat, monkeypatch):
    report, _ = serving.artifact()
    row = report['player_props'][stat]
    assert row['fit_policy'] == 'player_scale_only'
    assert row['fit_samples'] >= 100
    assert row['candidate']['samples'] >= 50 and row['candidate']['independent_games'] >= 20
    if stat == 'xp_made':
        assert row['deployable_experimental'] is False
        assert row['user_override_approved'] is True
        assert row['candidate']['gaussian_nll'] > row['baseline']['gaussian_nll']
    else:
        assert row['candidate']['gaussian_nll'] < row['baseline']['gaussian_nll']
    assert row['candidate']['rmse'] == row['baseline']['rmse']
    assert row['validation_passed'] is False
    mean, sigma, candidate = serving.prop_parameters(2., 1., 'ncaaf', stat, True)
    assert mean == 2. and .5 <= sigma <= 3. and candidate == serving.CANDIDATE_ID
    assert serving.prop_parameters(2., 1., 'ncaaf', stat, False) == (2., 1., None)
    assert serving.prop_parameters(2., 1., 'nfl', stat, True) == (2., 1., None)
    monkeypatch.setattr(serving, 'get_settings', lambda: SimpleNamespace(
        ncaaf_spread_calibration_enabled=True, ncaaf_prop_calibration_enabled=False))
    assert serving.prop_parameters(2., 1., 'ncaaf', stat, True) == (2., 1., None)


def test_v3_retains_all_previous_market_coefficients():
    previous = json.loads((serving.ARTIFACT_PATH.parent/'archive'/
        'ncaaf-distributions-20260905-v2.json').read_text())
    report, _ = serving.artifact()
    assert report['spread'] == previous['spread']
    for stat, row in previous['player_props'].items():
        assert report['player_props'][stat] == row


def test_manual_approval_cannot_bypass_parameter_bounds(tmp_path, monkeypatch):
    report, _ = serving.artifact()
    changed = json.loads(json.dumps(report))
    changed['player_props']['xp_made']['parameters']['scale_stddev'] = 99.
    path = tmp_path/'invalid-manual.json'
    path.write_text(json.dumps(changed))
    with monkeypatch.context() as patch:
        patch.setattr(serving, 'ARTIFACT_PATH', path)
        serving.artifact.cache_clear()
        assert serving.prop_parameters(2., 1., 'ncaaf', 'xp_made', True) == (2., 1., None)
    serving.artifact.cache_clear()


@pytest.mark.parametrize('stat', ['pass_rush_yards', 'passing_yards', 'receiving_touchdowns', 'rushing_attempts', 'rushing_touchdowns'])
def test_v2_families_are_fitted_scoped_and_pregame_only(stat):
    report, _ = serving.artifact()
    evidence = report['player_props'][stat]
    assert evidence['candidate']['rmse'] <= evidence['baseline']['rmse']
    assert evidence['candidate']['gaussian_nll'] < evidence['baseline']['gaussian_nll']
    mean, sigma, candidate = serving.prop_parameters(5, 2, 'ncaaf', stat, True)
    assert candidate == serving.CANDIDATE_ID and sigma > 0
    assert (mean, sigma) != (5, 2)
    assert serving.prop_parameters(5, 2, 'ncaaf', stat, False) == (5, 2, None)
    assert serving.prop_parameters(5, 2, 'nfl', stat, True) == (5, 2, None)


def test_corrupt_artifact_falls_back(tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        path = tmp_path/'bad.json'
        path.write_text('{')
        patch.setattr(serving, 'ARTIFACT_PATH', path)
        serving.artifact.cache_clear()
        assert serving.distribution_status()['artifact_available'] is False
        assert serving.spread_probability(3, -7, .25, 'ncaaf', True) == (.25, None)
        assert serving.prop_parameters(5, 2, 'ncaaf', 'receptions', True) == (5, 2, None)
    serving.artifact.cache_clear()


def test_fit_never_uses_holdout_to_choose_parameters():
    rows = [{'day': f'2025-{1+i//28:02d}-{1+i%28:02d}', 'game_id': str(i*10+j),
             'mean': 5., 'sigma': 2., 'value': 5+(j%3-1)*3.} for i in range(100) for j in range(10)]
    first = fit(rows, 'player')
    changed = [r | {'value': 1000} if r['day'] >= first['holdout_from'] else r for r in rows]
    second = fit(changed, 'player')
    assert first['parameters'] == second['parameters']
    assert first['fit_through'] < first['holdout_from']
    assert first['candidate'] != second['candidate']


def test_replay_excludes_same_day_and_legacy_alias():
    games, stats = [], []
    player, home, away = uuid4(), uuid4(), uuid4()
    for i in range(6):
        g = SimpleNamespace(id=uuid4(), game_time=datetime(2025, 1, 1, tzinfo=timezone.utc)+timedelta(days=min(i, 4)),
            home_team_id=home, away_team_id=away, home_score=20, away_score=10)
        games.append(g)
        stats.append(SimpleNamespace(game_id=g.id, player_id=player, stat_type='receptions', value=float(i)))
        stats.append(SimpleNamespace(game_id=g.id, player_id=player, stat_type='ints_thrown', value=1000.))
    _, props = replay(games, stats)
    assert [r['mean'] for r in props['receptions']] == [1.5, 1.5]
    assert 'ints_thrown' not in props


@pytest.mark.parametrize('stat', ['receptions', 'fg_made', 'xp_made', 'kicking_points'])
async def test_api_spread_and_prop_override_and_baseline(db, monkeypatch, stat):
    home = await resolve_team(db, 'Ohio State Buckeyes', sport='ncaaf')
    away = await resolve_team(db, 'Michigan Wolverines', sport='ncaaf')
    db.add_all([TeamRating(team_id=home.id, sport='ncaaf', rating=1600),
                TeamRating(team_id=away.id, sport='ncaaf', rating=1500)])
    game = Game(sport='ncaaf', season=2026, status='scheduled', home_team_id=home.id, away_team_id=away.id,
                game_time=datetime.now(timezone.utc)+timedelta(days=1))
    player = Player(sport='ncaaf', full_name='Test Receiver')
    db.add_all([game, player])
    await db.flush()
    for side, line in [('home', -7), ('away', 7)]:
        db.add(TeamMarketLine(game_id=game.id, source='test', market='spread', side=side,
            line=line, line_type='live', price_american=100, observed_at=datetime.now(timezone.utc)))
    for i in range(4):
        past = Game(sport='ncaaf', season=2025, status='final',
                    game_time=datetime.now(timezone.utc)-timedelta(days=i+2))
        db.add(past)
        await db.flush()
        db.add(PlayerGameStat(player_id=player.id, game_id=past.id, stat_type=stat, value=i+2))
    db.add(PlayerPropLine(player_id=player.id, game_id=game.id, source='test', stat_type=stat,
        line=4.5, over_price_american=100, under_price_american=100, observed_at=datetime.now(timezone.utc)))
    await db.commit()
    for kind, model in [('team', TeamMarketLine), ('prop', PlayerPropLine)]:
        for quote in (await db.scalars(select(model))).all():
            await confirm_quote(db, kind, quote)
    await db.commit()
    rows = await signal_rows(db, 'ncaaf')
    home_row = next(r for r in rows if r['selection'].startswith('Ohio'))
    baseline = spread_cover_probability(1600, 1500, -7, 'ncaaf')
    expected, _ = serving.spread_probability(implied_margin(1600, 1500), -7, baseline, 'ncaaf', True)
    assert home_row['model_probability'] == round(expected, 4)
    assert home_row['baseline_model_probability'] == round(baseline, 4)
    assert sum(r['model_probability'] for r in rows) == pytest.approx(1)
    prop = (await prop_rows(db, 'ncaaf'))[0]
    assert prop['calibration_candidate_id'] == serving.CANDIDATE_ID
    assert prop['model_probability'] == round(over_probability(prop['served_projection_mean'], prop['served_projection_stddev'], 4.5), 4)
    if stat == 'receptions':
        assert prop['projection'] != prop['baseline_projection']
    else:
        assert prop['projection'] == prop['baseline_projection']
    monkeypatch.setattr(serving, 'get_settings', lambda: SimpleNamespace(
        ncaaf_spread_calibration_enabled=False, ncaaf_prop_calibration_enabled=False))
    rolled = (await prop_rows(db, 'ncaaf'))[0]
    assert rolled['model_probability'] == rolled['baseline_model_probability']
    assert all(r['model_probability'] == r['baseline_model_probability'] for r in await signal_rows(db, 'ncaaf'))
