from datetime import datetime, timedelta, timezone
from src.services.history_candidates import candidates
import json
from scripts.evaluate_history_candidates import select_history_records


def history():
    now = datetime(2026, 9, 8, tzinfo=timezone.utc)
    return now, [{'game_id': str(i), 'time': now-timedelta(days=20-i), 'season': 2025 if i < 8 else 2026,
                  'game_type': 'REG', 'values': {'hits': i % 3, 'plate_appearances': 4}} for i in range(12)]


def test_asof_excludes_target_future_preseason_and_later_season():
    now, rows = history()
    expected, _ = candidates(rows, 'hits', 2026, now, .5)
    for extra in ({'time': now}, {'time': now+timedelta(days=1)}, {'season': 2027}, {'game_type': 'PRE'}):
        bogus = {**rows[0], 'values': {'hits': 10000}, **extra}
        assert candidates(rows+[bogus], 'hits', 2026, now, .5)[0] == expected


def test_season_prior_not_invented_and_control_remains_separate():
    now, rows = history()
    result, _ = candidates(rows, 'hits', 2026, now, .5)
    assert set(result) == {'repaired_history_control_v1', 'season_shrinkage_normal_v1', 'observed_workload_normal_v1'}
    assert all(0 <= p <= 1 for p in result.values())
    result, _ = candidates(rows[:8], 'hits', 2026, now, .5)
    assert 'season_shrinkage_normal_v1' not in result
    assert candidates(rows[:3], 'hits', 2026, now, .5)[0] == {}


def test_pitcher_needs_explicit_role_and_eight_paired_outings():
    now, rows = history()
    for row in rows:
        row['values'] = {'strikeouts': row['values']['hits'], 'pitching_outs': 15}
    result, reason = candidates(rows, 'strikeouts', 2026, now, 1.5)
    assert reason == 'missing_pitcher_role' and 'observed_workload_normal_v1' not in result
    for row in rows:
        row['values']['pitching_games_started'] = 1
    assert 'observed_workload_normal_v1' in candidates(rows, 'strikeouts', 2026, now, 1.5)[0]
    rows[-1]['values']['pitching_games_started'] = 0
    assert 'observed_workload_normal_v1' not in candidates(rows, 'strikeouts', 2026, now, 1.5)[0]


def test_constant_and_nonfinite_inputs_fail_closed():
    now, rows = history()
    assert candidates(rows, 'hits', 2026, now, float('nan'))[0] == {}
    for r in rows:
        r['values']['hits'] = 1
    assert candidates(rows, 'hits', 2026, now, .5)[0] == {}


def test_verified_zero_opportunities_not_dropped():
    now, rows = history()
    rows = rows[:8]
    rows[-1]['values'] = {'hits': 0, 'plate_appearances': 0}
    result, _ = candidates(rows, 'hits', 2026, now, .5)
    assert 'observed_workload_normal_v1' in result  # eight pairs, including zero
    for r in rows:
        r['values']['plate_appearances'] = 0
    assert 'observed_workload_normal_v1' not in candidates(rows, 'hits', 2026, now, .5)[0]


def test_compact_selection_keeps_earliest_baseline_not_features(tmp_path):
    for i in range(2):
        record = {'kind': 'player', 'game_id': 'g', 'player_id': 'p', 'market': 'hits',
            'quote_id': 'q', 'line': .5, 'feature_snapshot': {'unused': [1]*1000},
            'prediction': {'baseline_model_probability': .3+i*.1, 'model_probability': .9}}
        (tmp_path/f'{i}.json').write_text(json.dumps({'schema_version': 1,
            'captured_at': f'2026-09-0{4+i}T00:00:00+00:00', 'records': [record]}))
    selected = select_history_records(tmp_path)
    assert len(selected) == 1
    saved = next(iter(selected.values()))[1]
    assert saved['prediction'] == {'baseline_model_probability': .3}
    assert 'feature_snapshot' not in saved
