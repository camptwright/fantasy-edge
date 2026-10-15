import json
from pathlib import Path
from src.services.release_manifest import build, status, model_artifacts


def tree(tmp_path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'app.py').write_text('VALUE = 1\n')
    (tmp_path / 'requirements-runtime.lock').write_text('')
    (tmp_path / '.env').write_text('API_KEY=must-not-be-read')
    return tmp_path


def test_seal_detects_source_drift_and_ignores_secrets(tmp_path):
    root = tree(tmp_path)
    seal = build(root)
    (root / 'release-manifest.json').write_text(json.dumps(seal))
    assert status(root)['status'] == 'matched'
    (root / '.env').write_text('API_KEY=different')
    assert build(root)['release_id'] == seal['release_id']
    (root / 'src' / 'app.py').write_text('VALUE = 2\n')
    assert status(root)['status'] == 'drift'


def test_tampered_manifest_is_invalid(tmp_path):
    root = tree(tmp_path)
    seal = build(root)
    seal['release_id'] = 'tampered'
    (root / 'release-manifest.json').write_text(json.dumps(seal))
    assert status(root)['status'] == 'invalid_seal'


def test_packaged_model_bytes_are_part_of_release(tmp_path):
    root = tree(tmp_path)
    models = root / 'models'
    models.mkdir()
    (models / 'candidate.json').write_text('{"version":1}')
    first = build(root)
    (models / 'candidate.json').write_text('{"version":2}')
    assert first['release_id'] != build(root)['release_id']
    (models / '.env').write_text('secret')
    assert model_artifacts(models)['files'] == 1
