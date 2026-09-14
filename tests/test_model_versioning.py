from datetime import datetime, timezone, timedelta
from src.services.model_version import semantic_hash, manifest
from src.services.evaluation_status import completed_today, status


def test_comment_and_formatting_do_not_change_semantics():
    assert semantic_hash('def f(x):\n return x+1\n') == semantic_hash('def f(x):\n "doc"\n # comment\n return x + 1\n')


def test_unrelated_route_does_not_change_serving_version():
    source = 'def serving(x):\n return x+1\n'
    assert semantic_hash(source, {'serving'}) == semantic_hash(source+'\ndef status():\n return 123\n', {'serving'})
    assert semantic_hash(source, {'serving'}) != semantic_hash(source.replace('x+1','x+2'), {'serving'})


def test_manifest_repeatable_and_separate_policy():
    first, second = manifest(), manifest()
    assert first == second
    assert first['model_version'] != first['policy_version']
    assert first['cohort_version'] != first['model_version']


def test_daily_success_requires_complete_same_day_and_sports():
    now = datetime.now(timezone.utc)
    report = {'status': 'complete', 'completed_at': now.isoformat(), 'sports': {'nfl': {}}}
    assert completed_today(report, ['nfl'], now)
    assert not completed_today({**report, 'status': 'partial'}, ['nfl'], now)
    assert not completed_today(report, ['nfl','mlb'], now)
    assert not completed_today(report, ['nfl'], now+timedelta(days=1))
    assert not completed_today(report, ['nfl'], now-timedelta(seconds=1))


def test_missing_evaluation_is_overdue(tmp_path):
    assert status(tmp_path, ['nfl'])['status'] == 'overdue_or_incomplete'


def test_new_policy_cohorts_stay_separate_from_legacy(tmp_path):
    import json
    import uuid
    from src.services.forecast_grading import load_cohort
    record = {'game_id': str(uuid.uuid4()), 'kind': 'team', 'market': 'moneyline', 'quote_id': 'q'}
    for i, cohort in enumerate([None, 'policy-one', 'policy-two']):
        payload = {'schema_version': 1, 'captured_at': datetime.now(timezone.utc).isoformat(),
                   'model_version': 'same-model', 'records': [record]}
        if cohort:
            payload['cohort_version'] = cohort
        (tmp_path/f'{i}.json').write_text(json.dumps(payload))
    selected, _, _ = load_cohort(tmp_path)
    assert {key[0] for key in selected} == {'same-model', 'policy-one', 'policy-two'}
