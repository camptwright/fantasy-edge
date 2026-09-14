import json
from datetime import datetime, timezone, timedelta
import pytest
from scripts.evaluate_prop_candidates import ablations, select_records, summarize


def record():
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    return {'kind': 'player', 'game_id': 'game', 'player_id': 'player', 'market': 'receptions', 'line': 2.5,
        'quote_id': 'q', 'prediction': {'baseline_model_probability': .4, 'model_probability': .8},
        'inputs': {'stddev': 2}, 'feature_snapshot': {'mean': 2, 'recent_mean': 4, 'variance': 4,
        'canonical_stat': 'receptions', 'as_of': now.isoformat(), 'last_result_at': (now-timedelta(days=1)).isoformat(),
        'opportunity': None}}


def test_isolate_recency_from_discrete_mean():
    rows = ablations(record())
    assert rows['reconstructed:recency_normal_v1'] > .5
    assert 'reconstructed:opportunity_normal_v1' not in rows
    assert 0 <= rows['reconstructed:count_only_v1'] <= 1


def test_earliest_pair_preserves_retained_not_served_baseline(tmp_path):
    for index in range(2):
        r = record()
        r['prediction']['baseline_model_probability'] = .4+index*.1
        (tmp_path/f'{index}.json').write_text(json.dumps({'schema_version': 1,
            'captured_at': f'2026-09-05T0{index}:01:00+00:00', 'records': [r]}))
    selected, _ = select_records(tmp_path)
    assert len(selected) == 2
    assert all(value[3] == .4 for value in selected.values())


def test_clusters_and_sign_are_correct():
    rows = [{'game_id': 'a', 'candidate': .9, 'baseline': .5, 'outcome': 1}]*10
    report = summarize(rows)
    assert report['samples'] == 10 and report['independent_games'] == 1
    assert report['delta_brier'] == pytest.approx(-.24)
    assert report['game_cluster_delta_brier_95pct'] is None
    assert not report['promotion_eligible']


def test_missing_baseline_is_not_substituted(tmp_path):
    r = record()
    del r['prediction']['baseline_model_probability']
    (tmp_path/'1.json').write_text(json.dumps({'schema_version': 1, 'captured_at': '2026-09-05T01:00:00+00:00', 'records': [r]}))
    selected, excluded = select_records(tmp_path)
    assert selected == {} and excluded['missing_retained_baseline_capture_rows'] == 1
