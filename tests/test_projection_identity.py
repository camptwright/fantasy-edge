import json
import pytest
from src.services import projection_identity as identity

RUNTIME = {'python': '3.12', 'numpy': 'test', 'scipy': 'test', 'sqlalchemy': 'test'}


@pytest.fixture
def sources(tmp_path):
    names = set(identity.PREDICTION) | set(identity.CAPTURE) | set(identity.EVALUATOR)
    paths = [f'src/services/{name}.py' for name in names] + [
        'config/nfl_player_lab_ids.json', 'src/ingest/espn_fantasy_constants.py']
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((identity.ROOT / path).read_text())
    return tmp_path


def change(root, name, before, after):
    path = root / 'src/services' / f'{name}.py'
    source = path.read_text()
    assert before in source
    path.write_text(source.replace(before, after, 1))


def test_grade_edit_changes_evaluator_not_prediction_or_cohort(sources):
    before = identity.manifest(sources, RUNTIME)
    change(sources, 'fantasy_prospective', "'baseline_error':abs(actual-record['prediction']['baseline_subtotal'])",
           "'baseline_error':2*abs(actual-record['prediction']['baseline_subtotal'])")
    after = identity.manifest(sources, RUNTIME)
    assert before['prediction_version'] == after['prediction_version']
    assert before['cohort_version'] == after['cohort_version']
    assert before['evaluator_version'] != after['evaluator_version']
    assert before['manifest_id'] != after['manifest_id']


def test_prediction_change_resets_cohort(sources):
    before = identity.manifest(sources, RUNTIME)
    change(sources, 'roster_stat_model', 'raw = .5*baseline', 'raw = .6*baseline')
    after = identity.manifest(sources, RUNTIME)
    assert before['prediction_version'] != after['prediction_version']
    assert before['cohort_version'] != after['cohort_version']


def test_game_availability_rules_are_versioned(sources):
    before=identity.manifest(sources,RUNTIME)
    change(sources,'injury_evidence','<= 86400','<= 43200')
    after=identity.manifest(sources,RUNTIME)
    assert before['prediction_version'] != after['prediction_version']
    assert before['cohort_version'] != after['cohort_version']


def test_capture_change_resets_cohort_not_prediction(sources):
    before = identity.manifest(sources, RUNTIME)
    change(sources, 'fantasy_prospective', 'timedelta(hours=72)', 'timedelta(hours=48)')
    after = identity.manifest(sources, RUNTIME)
    assert before['prediction_version'] == after['prediction_version']
    assert before['capture_version'] != after['capture_version']
    assert before['cohort_version'] != after['cohort_version']


def test_comments_and_docs_do_not_reset_cohorts(sources):
    before = identity.manifest(sources, RUNTIME)
    change(sources, 'fantasy_simulation', 'Deterministic empirical research', 'Updated documentation')
    path = sources / 'src/services/fantasy_decision_models.py'
    path.write_text('# A reporting comment\n' + path.read_text())
    assert identity.manifest(sources, RUNTIME) == before


def test_local_helpers_and_constants_are_versioned():
    source = 'SCALE = 2\ndef helper(x):\n return x*SCALE\ndef predict(x):\n return helper(x)\ndef grade(x):\n return x\n'
    base = identity.semantic_component(source, {'predict'})
    assert identity.semantic_component(source.replace('return x*SCALE', 'return x+SCALE'), {'predict'}) != base
    assert identity.semantic_component(source.replace('SCALE = 2', 'SCALE = 3'), {'predict'}) != base
    assert identity.semantic_component(source.replace('def grade(x):\n return x', 'def grade(x):\n return x+1'), {'predict'}) == base
    with pytest.raises(ValueError):
        identity.semantic_component(source, {'missing'})


def test_untracked_prediction_import_is_rejected(sources):
    path = sources / 'src/services/fantasy_decision_models.py'
    path.write_text(path.read_text() + '\nfrom src.services.untracked_model import predict\n')
    with pytest.raises(ValueError, match='Unversioned prediction dependency'):
        identity.manifest(sources, RUNTIME)


def test_identity_mapping_and_runtime_are_versioned(sources):
    before = identity.manifest(sources, RUNTIME)
    after = identity.manifest(sources, {**RUNTIME, 'numpy': 'changed'})
    assert after['cohort_version'] != before['cohort_version']
    path = sources / 'config/nfl_player_lab_ids.json'
    data = json.loads(path.read_text())
    data['test_identity_change'] = True
    path.write_text(json.dumps(data))
    assert identity.manifest(sources, RUNTIME)['cohort_version'] != before['cohort_version']


def test_registry_is_create_only_and_rejects_conflicts(tmp_path):
    record = identity.manifest(runtime=RUNTIME)
    path = identity.archive_identity(tmp_path, record)
    assert identity.archive_identity(tmp_path, record) == path
    path.write_text('{}')
    with pytest.raises(ValueError, match='conflicts'):
        identity.archive_identity(tmp_path, record)


def test_existing_legacy_forecast_version_is_not_relabelled():
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace
    from src.services.fantasy_prospective import grade
    now = datetime.now(timezone.utc)
    record = {'id': 'old', 'game_id': 'g', 'version': 'legacy-byte-hash', 'league_id': 'league',
        'scoring_cohort': 'rules', 'captured_at': (now-timedelta(days=2)).isoformat(),
        'prediction': {'status': 'candidate', 'scoring_weights': {'yards': 1},
                       'baseline_subtotal': 10, 'modeled_subtotal': 11}}
    result = grade(record, SimpleNamespace(id='g', status='final', game_time=now-timedelta(days=1)), {'yards': 12})
    assert result['version'] == 'legacy-byte-hash'
    assert result['status'] == 'graded'


async def test_new_captures_reference_manifest_and_do_not_duplicate(tmp_path, monkeypatch):
    from datetime import datetime, timezone, timedelta
    from types import SimpleNamespace
    from src.services import fantasy_prospective as prospective
    record = identity.manifest(runtime=RUNTIME)
    identity.archive_identity(tmp_path, record)
    lab = {'status': 'candidate', 'league_id': 'league', 'scoring_settings': {'rec': 1},
        'coverage': {'stale_inputs': False, 'weekly_decisions_open': False},
        'players': [{'canonical_player_id': 'player', 'player_id': 'platform-player', 'name': 'Test',
            'ros': {'full_ros_value': None, 'per_game': {'status': 'candidate', 'scoring_weights': {'receptions': 1}}},
            'next_games': [{'id': 'game', 'status': 'scheduled',
                            'kickoff': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}]}]}
    async def build(*args):
        return lab
    monkeypatch.setattr(prospective, 'build', build)
    leagues = [SimpleNamespace(league_id='league', season='2026')]
    first, errors = await prospective.capture_forecasts(None, tmp_path, leagues, record)
    second, _ = await prospective.capture_forecasts(None, tmp_path, leagues, record)
    assert first == 1 and second == 0 and errors == {}
    captured = json.loads(next((tmp_path/'forecasts').glob('*.json')).read_text())
    assert captured['version'] == record['cohort_version']
    assert captured['model_identity'] == identity.reference(record)


async def test_prospective_task_runs_twice_with_fresh_loops(db, tmp_path, monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from tests.conftest import TEST_DB_URL
    from src.scheduler.calibration import fantasy_prospective as task
    from src.services import fantasy_prospective as prospective
    @asynccontextmanager
    async def sessions():
        engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()
    monkeypatch.setattr(prospective, 'get_worker_db', sessions)
    monkeypatch.setattr(prospective, 'get_settings', lambda: SimpleNamespace(raw_archive_dir=tmp_path))
    results = [await asyncio.to_thread(task.run) for _ in range(2)]
    assert all(result['evaluation_identity']['cohort_version'] == prospective.version() for result in results)
    root = tmp_path/'fantasy-prospective'
    assert len(list((root/'manifests').glob('*.json'))) == 1
    assert len(list((root/'reports').glob('*.json'))) == 2
