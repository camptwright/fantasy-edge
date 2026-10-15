"""Content-sealed backend release identity; no environment or secret files."""
import hashlib
import json
import platform
from pathlib import Path

from scripts.release_audit import dependency_drift, differences, source_files

SCHEMA = 1


def fingerprint(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def model_artifacts(directory):
    directory = Path(directory)
    files = {}
    if not directory.is_dir() or directory.is_symlink():
        return {'fingerprint': fingerprint(files), 'files': 0, 'status': 'no_packaged_artifacts'}
    for path in sorted(directory.rglob('*')):
        relative = path.relative_to(directory)
        if not path.is_file() or path.is_symlink() or any(p.startswith('.') for p in relative.parts):
            continue
        if path.suffix not in {'.json', '.pkl', '.pickle', '.joblib', '.ubj', '.bin', '.onnx', '.pt'}:
            continue
        files[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'fingerprint': fingerprint(files), 'files': len(files),
            'status': 'observed' if files else 'no_packaged_artifacts'}


def build(root, *, artifacts_directory=None):
    root = Path(root)
    files = source_files(root)
    packaged = model_artifacts(artifacts_directory or root / 'models')
    identity = {'schema': SCHEMA, 'files': files,
                'python': platform.python_version(), 'packaged_models': packaged}
    return {**identity, 'release_id': fingerprint(identity),
            'scope': 'Backend source, pinned dependency lock, Python runtime, and packaged model bytes. Live model observations are reported separately.'}


def status(root=None, *, artifacts_directory=None):
    root = Path(root or Path(__file__).resolve().parents[2])
    path = root / 'release-manifest.json'
    base = {'schema': SCHEMA, 'release_id': None, 'status': 'missing_seal'}
    try:
        seal = json.loads(path.read_text())
        identity = {k: seal[k] for k in ('schema', 'files', 'python', 'packaged_models')}
        if seal['schema'] != SCHEMA or fingerprint(identity) != seal['release_id']:
            return {**base, 'status': 'invalid_seal'}
        from importlib.metadata import distributions
        packages = {d.metadata['Name']: d.version for d in distributions()}
        drift = differences(seal['files'], source_files(root))
        deps = dependency_drift(root, packages)
        python_matches = seal['python'] == platform.python_version()
        packaged = model_artifacts(root / 'models')
        model_matches = packaged == seal['packaged_models']
        live = model_artifacts(artifacts_directory) if artifacts_directory is not None else None
        return {'schema': SCHEMA, 'release_id': seal['release_id'],
                'status': 'matched' if not any(drift.values()) and not deps and python_matches and model_matches else 'drift',
                'source_files_checked': len(seal['files']), 'source': drift,
                'dependency_drift': deps, 'python_matches': python_matches,
                'packaged_models_match': model_matches, 'live_models': live,
                'qualification': 'Model fingerprints identify bytes; qualification remains in prospective reports.'}
    except FileNotFoundError:
        return base
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {**base, 'status': 'invalid_seal'}
