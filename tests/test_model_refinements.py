from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import math
import json
import pytest

from src.services.prospective_review import scorecard
from src.services.shadow_props import probabilities, count_distribution, predict
from src.services.stat_identity import canonical_results
from src.services.player_features import snapshots
from src.services.projections import project_stats
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player
from src.services.forecast_capture import capture
from src.services.forecast_grading import grade
from src.services.model_coverage import coverage
from src.models.facts import PlayerPropLine
from src.services.quote_eligibility import confirm_quote


def observations():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [{'game_id': str(i), 'market_key': 'receptions:p', 'captured_at': start+timedelta(days=i%20),
        'outcome': i%2, 'status': 'graded', 'probability': .8 if i%2 else .2,
        'baseline': .5, 'market_probability': .6 if i%2 else .4, 'protocol_verified': True}
        for i in range(220)]


def test_paired_fixed_window_cannot_promote_early():
    rows = observations()
    report = scorecard(rows, datetime(2026, 1, 25, tzinfo=timezone.utc))
    assert not report['review']['promotion_eligible']
    assert 'fixed_evaluation_window_not_closed' in report['review']['blockers']
    final = scorecard(rows, datetime(2026, 2, 10, tzinfo=timezone.utc))
    assert final['review']['promotion_eligible']
    assert final['automatic_deployment'] is False
    assert final['review']['brier_delta_interval_95'][1] < 0
    assert sum(b['samples'] for b in final['reliability_bins']) == 220


def test_missing_pairs_and_unresolved_outcomes_block_review():
    rows = observations()
    rows[0]['baseline'] = None
    rows[1]['market_probability'] = None
    rows[2]['outcome'], rows[2]['status'] = None, 'missing_result'
    report = scorecard(rows, datetime(2026, 2, 10, tzinfo=timezone.utc))
    assert not report['review']['promotion_eligible']
    assert 'paired_baseline_incomplete' in report['review']['blockers']
    assert 'unresolved_window_outcomes' in report['review']['blockers']
    assert 'market_benchmark_missing' in report['review']['blockers']
    assert report['paired_candidate']['samples'] == report['paired_baseline']['samples']


@pytest.mark.parametrize('mean,var,line', [(2.,2.,1.), (2.,5.,1.5), (0.,0.,0.), (2.,3.,-1.)])
def test_count_probability_mass_and_push_contract(mean, var, line):
    dist, _ = count_distribution(mean, var)
    p = probabilities(dist, line)
    assert p['over_probability']+p['under_probability']+p['push_probability'] == pytest.approx(1)
    if not float(line).is_integer():
        assert p['push_probability'] == 0
    if p['model_probability'] is not None:
        assert 0 <= p['model_probability'] <= 1


def test_compound_kicking_respects_scoring_and_stays_shadow():
    f = {'mean': 6., 'variance': 5., 'recent_mean': 6., 'canonical_stat': 'kicking_points',
        'opportunity': None, 'components': {
            'fg_made': {'mean': 1., 'recent_mean': 1., 'variance': 1.},
            'xp_made': {'mean': 0., 'recent_mean': 0., 'variance': 0.}}}
    output = predict(f, 1., 2.)['compound_kicking_v1']
    assert output['push_probability'] == 0.  # No way to score 1 with XP fixed at zero.
    assert output['under_probability'] == pytest.approx(math.exp(-1), abs=1e-8)
    assert output['status'] == 'shadow_only'


def test_aliases_never_double_count_an_outcome():
    rows = [SimpleNamespace(player_id='p', game_id='g', stat_type='ints_thrown', value=1.),
            SimpleNamespace(player_id='p', game_id='g', stat_type='passing_interceptions', value=1.)]
    assert canonical_results(rows) == {('p', 'g', 'passing_interceptions'): 1.}


async def test_asof_features_exclude_future_results_and_capture_usage(db):
    now = datetime.now(timezone.utc)
    player = Player(sport='nfl', full_name='Feature Player')
    db.add(player)
    await db.flush()
    for i in range(6):
        time = now+timedelta(days=1) if i == 5 else now-timedelta(days=10+i)
        game = Game(sport='nfl', season=2026, status='final', game_time=time)
        db.add(game)
        await db.flush()
        db.add_all([PlayerGameStat(player_id=player.id, game_id=game.id, stat_type='passing_yards', value=9999. if i == 5 else 100.+i*10),
                    PlayerGameStat(player_id=player.id, game_id=game.id, stat_type='passing_attempts', value=20.+i)])
    await db.commit()
    result = await snapshots(db, [{'id': 'quote', 'player_id': str(player.id), 'stat_type': 'passing_yards'}], now)
    f = result['quote']
    assert f['games'] == 5 and f['mean'] == 120.
    assert f['opportunity']['paired_games'] == 5
    assert f['as_of'] == now.isoformat()
    assert 'injury_status' in f['missing_context']


async def test_alias_projection_uses_unique_canonical_history(db):
    player = Player(sport='ncaaf', full_name='Alias Player')
    db.add(player)
    await db.flush()
    for i in range(4):
        game = Game(sport='ncaaf', season=2026, status='final',
                    game_time=datetime.now(timezone.utc)-timedelta(days=i+1))
        db.add(game)
        await db.flush()
        db.add_all([PlayerGameStat(player_id=player.id, game_id=game.id, stat_type=s, value=float(i))
                    for s in ('ints_thrown', 'passing_interceptions')])
    await db.commit()
    result = await project_stats(db, {(player.id, 'ints_thrown'), (player.id, 'passing_interceptions')})
    assert result[(player.id, 'ints_thrown')] == result[(player.id, 'passing_interceptions')]
    assert result[(player.id, 'ints_thrown')][0] == 1.5


async def test_shadow_capture_grades_separately_and_does_not_change_serving(db, tmp_path):
    from src.api.routers.sportsbook import prop_rows
    now = datetime.now(timezone.utc)
    player = Player(sport='ncaaf', full_name='Shadow Capture')
    game = Game(sport='ncaaf', season=2026, status='scheduled', game_time=now+timedelta(days=1))
    db.add_all([player, game])
    await db.flush()
    for i in range(4):
        past = Game(sport='ncaaf', season=2025, status='final', game_time=now-timedelta(days=30+i))
        db.add(past)
        await db.flush()
        db.add(PlayerGameStat(player_id=player.id, game_id=past.id, stat_type='receptions', value=1.+i))
    quote = PlayerPropLine(player_id=player.id, game_id=game.id, stat_type='receptions', line=2.5,
        source='test', over_price_american=-110, under_price_american=-110, observed_at=now)
    db.add(quote)
    await db.flush()
    await confirm_quote(db, 'prop', quote)
    await db.commit()
    payload = await capture(db)
    assert len(payload['records']) == 1
    record = payload['records'][0]
    assert len(record['shadow_predictions']) == 2
    assert all(s['comparison_baseline'] == 'retained_baseline' for s in record['shadow_predictions'].values())
    assert record['feature_snapshot']['as_of'] < payload['captured_at']
    current = (await prop_rows(db, 'ncaaf'))[0]
    assert record['prediction']['model_probability'] == current['model_probability']
    assert current['market_fair_probability'] == pytest.approx(.5)
    report = await coverage(db, [current])
    assert next(r for r in report['families'] if r['stat_type']=='receptions')['actionable_quotes'] == 0
    gid, pid = game.id, player.id
    await db.rollback()
    game = await db.get(Game, gid)
    game.status = 'final'
    db.add(PlayerGameStat(player_id=pid, game_id=gid, stat_type='receptions', value=3.))
    await db.commit()
    (tmp_path/'capture.json').write_text(json.dumps(payload, allow_nan=False))
    result = await grade(db, tmp_path)
    assert result['counts'] == {'graded': 1}  # Shadows do not inflate serving counts.
    assert len(result['shadow_reports']) == 2
    # Research results remain graded, but uncorroborated fixtures cannot enter
    # the new verified prospective promotion cohort.
    assert result['reports'][0]['prospective_scorecard']['paired_candidate']['samples'] == 0
    assert result['reports'][0]['prospective_scorecard']['unverified_records_excluded'] == 1
    assert all(r['scorecard']['paired_candidate']['samples'] == 0 for r in result['shadow_reports'])
