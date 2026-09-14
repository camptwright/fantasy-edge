from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import select
from src.ingest.ncaaf_composites import composite_values, derive_composites
from src.ingest.ncaaf_player_stats import made_attempts
from src.ingest.ncaaf_results import backfill_prop_results
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player, PlayerExternalId
from src.services.prop_readiness import readiness
from src.services.ncaaf_candidate_training import fit
from src.services.forecast_grading import outcome


def test_composites_require_every_observed_component():
    assert composite_values({'passing_yards': 200}) == {}
    assert composite_values({'passing_yards': 200, 'rushing_yards': -3}) == {'pass_rush_yards': 197}
    assert composite_values({'rushing_yards': 0, 'receiving_yards': 10}) == {'rush_rec_yards': 10}
    assert composite_values({'rushing_touchdowns': 0, 'receiving_touchdowns': 0}) == {'rush_rec_tds': 0}
    assert composite_values({'rushing_yards': float('nan'), 'receiving_yards': 10}) == {}


@pytest.mark.parametrize('value', ['3/2', '--', 'NaN/4', '1.5/2', '-1/3', '1/2/3'])
def test_compound_rejects_invalid_count(value):
    assert made_attempts(value) is None


def test_compound_zero_is_observed_not_missing():
    assert made_attempts('0/0') == (0, 0)
    assert made_attempts('2/3') == (2, 3)


async def test_backfill_is_idempotent_and_composites_are_exact(db, monkeypatch, tmp_path):
    from types import SimpleNamespace
    monkeypatch.setattr('src.scheduler.calibration.get_settings',
                        lambda: SimpleNamespace(raw_archive_dir=str(tmp_path)))
    g = Game(sport='ncaaf', season=2025, status='final', espn_event_id='123', game_time=datetime.now(timezone.utc))
    player = Player(sport='ncaaf', full_name='Test Player')
    db.add_all([g, player])
    await db.flush()
    db.add(PlayerExternalId(source='espn_ncaaf', external_id='1', player_id=player.id))
    await db.commit()
    def category(name, keys, values):
        return {'name': name, 'keys': keys, 'athletes': [{'athlete': {'id': '1', 'displayName': 'Test Player'}, 'stats': values}]}
    cats = [category('passing', ['passingYards'], ['200']),
            category('rushing', ['rushingYards'], ['-3']),
            category('kicking', ['fieldGoalsMade/fieldGoalAttempts', 'extraPointsMade/extraPointAttempts', 'totalKickingPoints'], ['2/3', '3/3', '9'])]
    payload = {'header': {'competitions': [{'id': '123', 'status': {'type': {'completed': True}}}]},
               'boxscore': {'players': [{'statistics': cats}, {'statistics': cats}]}}
    calls = []
    async def get(self, url, **kwargs):
        calls.append(url)
        return httpx.Response(200, json=payload, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    assert (await backfill_prop_results(db))['rows_written'] == 8  # includes FG/XP attempts
    assert (await backfill_prop_results(db))['games'] == 0
    assert len(calls) == 1
    assert await derive_composites(db) == 0
    facts = {s.stat_type: s.value for s in (await db.scalars(select(PlayerGameStat))).all()}
    assert facts['pass_rush_yards'] == 197 and facts['kicking_points'] == 9
    assert facts['fg_made'] == 2 and facts['xp_made'] == 3
    assert 'rush_rec_yards' not in facts


def test_readiness_does_not_equate_candidate_to_deployment():
    quotes = [{'stat_type': 'receptions', 'model_probability': .6}, {'stat_type': 'first_td_scorer'}]
    research = {'player_props': {'receptions': {'deployable_experimental': True}}}
    rows = {r['stat_type']: r for r in readiness(quotes, {}, research)['families']}
    assert rows['receptions']['status'] == 'candidate_review'
    assert rows['first_td_scorer']['status'] == 'unsupported'
    assert rows['passing_yards']['status'] == 'insufficient_evidence'


def test_manual_xp_override_exposes_failed_pinned_screen():
    quotes = [{'stat_type': 'xp_made', 'model_probability': .6, 'calibration_candidate_id': 'v3'}]
    # A newer successful research run must not relabel the failed deployed fit.
    research = {'player_props': {'xp_made': {'deployable_experimental': True}}}
    row = next(r for r in readiness(quotes, {}, research)['families'] if r['stat_type'] == 'xp_made')
    assert row['status'] == 'experimental_override'
    assert 'failed historical' in row['reason']
    assert row['deployment_evidence']['deployable_experimental'] is False


def test_research_holds_out_samples_without_splitting_a_day():
    rows = [{'day': f'2025-11-{i+1:02d}', 'game_id': f'{i}-{j}', 'mean': 5.,
             'sigma': 2., 'value': float(j%10)} for i in range(20) for j in range(50 if i < 8 else 1)]
    result = fit(rows, 'player')
    assert result['status'] == 'experimental_holdout'
    assert result['candidate']['samples'] >= .3*len(rows)
    assert result['fit_through'] < result['holdout_from']
    changed = [r | {'value': 1000.} if r['day'] >= result['holdout_from'] else r for r in rows]
    assert fit(changed, 'player')['parameters'] == result['parameters']


def test_kicking_scale_fit_preserves_mean_and_holdout_independence():
    rows = [{'day': f'2025-11-{i+1:02d}', 'game_id': f'{i}-{j}', 'mean': 3.,
             'sigma': 1., 'value': float(j % 2)*6} for i in range(20) for j in range(20)]
    result = fit(rows, 'player_scale_only')
    assert result['fit_policy'] == 'player_scale_only'
    assert result['parameters'] == {'bias_stddev': 0., 'scale_stddev': 3.}
    assert result['candidate']['rmse'] == result['baseline']['rmse']
    assert result['candidate']['gaussian_nll'] < result['baseline']['gaussian_nll']
    assert result['deployable_experimental'] is True
    changed = [r | {'value': 999.} if r['day'] >= result['holdout_from'] else r for r in rows]
    assert fit(changed, 'player_scale_only')['parameters'] == result['parameters']
    assert fit(rows[:50], 'player_scale_only')['deployable_experimental'] is False


def test_scale_fit_can_fail_holdout_without_weakening_gate():
    rows = [{'day': f'2025-11-{i+1:02d}', 'game_id': f'{i}-{j}', 'mean': 3.,
             'sigma': 1., 'value': float(j % 2)*6} for i in range(20) for j in range(20)]
    cutoff = fit(rows, 'player_scale_only')['holdout_from']
    # Uncertainty inflation learned on the fit period is harmful when all
    # held-out values equal their projected means. It must not be approved.
    changed = [r | {'value': 3.} if r['day'] >= cutoff else r for r in rows]
    result = fit(changed, 'player_scale_only')
    assert result['parameters']['scale_stddev'] == 3.
    assert result['candidate']['rmse'] == result['baseline']['rmse'] == 0.
    assert result['deployable_experimental'] is False


@pytest.mark.parametrize('stat', ['fg_made', 'xp_made', 'kicking_points'])
def test_kicking_grading_distinguishes_zero_push_and_missing(stat):
    now = datetime.now(timezone.utc)
    game = SimpleNamespace(status='final', game_time=now+timedelta(hours=1))
    record = {'kind': 'player', 'market': stat, 'player_id': 'p', 'game_id': 'g', 'line': 1.}
    assert outcome(record, game, {}, now) == ('missing_result', None)
    assert outcome(record, game, {('p', 'g', stat): 0.}, now) == ('graded', 0)
    assert outcome(record, game, {('p', 'g', stat): 1.}, now) == ('push', None)
    assert outcome(record, game, {('p', 'g', stat): 2.}, now) == ('graded', 1)
