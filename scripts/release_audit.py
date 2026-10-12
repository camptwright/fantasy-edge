"""Read-only backend release drift audit; never reads environment/secrets.

Run: python scripts/release_audit.py --context colima
Add --workspace to check the isolated preview API and observer instead.
Exit 1 means drift, unavailable containers, or missing dependency evidence.
Dashboard source is not present in its standalone image and is excluded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

TREES = ('src', 'config', 'alembic', 'scripts')
FILES = ('pyproject.toml', 'requirements-runtime.lock', 'alembic.ini')


def source_files(root):
    files = [root / name for name in FILES]
    for name in TREES:
        files.extend((root / name).rglob('*'))
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
        if path.is_file() and not path.is_symlink()
        and not any(part.startswith('.') or part == '__pycache__'
                    for part in path.relative_to(root).parts)
        and path.suffix in {'.py', '.yaml', '.yml', '.json', '.toml', '.ini', '.lock'}
    }


def differences(expected, actual):
    return {
        'missing': sorted(expected.keys() - actual.keys()),
        'unexpected': sorted(actual.keys() - expected.keys()),
        'changed': sorted(key for key in expected.keys() & actual.keys()
                          if expected[key] != actual[key]),
    }


def normalized(name):
    import re
    return re.sub(r'[-_.]+', '-', name).lower()


def dependency_drift(root, installed):
    installed = {normalized(k): v for k, v in installed.items()}
    failures = []
    for line in (root / 'requirements-runtime.lock').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        name, version = line.split('==')
        actual = installed.get(normalized(name))
        if actual != version:
            failures.append({'package': name, 'expected': version, 'installed': actual})
    return failures


def remote_probe():
    probe = Path(__file__).read_text().rsplit("\nif __name__ == '__main__':", 1)[0]
    return probe + "\nfrom importlib.metadata import distributions\nprint(json.dumps({'files':source_files(Path('/app')), 'packages':{d.metadata['Name']:d.version for d in distributions()}}))\n"


def targets(workspace):
    return (['-f', 'docker-compose.workspace.yml'], ('workspace-api', 'workspace-observer')) if workspace else (
        [], ('api', 'worker', 'evaluation', 'beat'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', default='colima')
    parser.add_argument('--workspace', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    expected = source_files(root)
    # Send this trusted audit implementation over stdin, so old containers do
    # not need the new script installed. No shell interpolation or env dump.
    probe = remote_probe()
    report = {'scope': 'Backend source and pinned runtime packages only; not database, dashboard, OS or model qualification.', 'services': {}}
    compose_args, services = targets(args.workspace)
    for service in services:
        try:
            result = subprocess.run(
                ['docker', '--context', args.context, 'compose', *compose_args, 'exec', '-T', service, 'python', '-'],
                input=probe, cwd=root, text=True, capture_output=True, timeout=30, check=True)
            actual = json.loads(result.stdout)
            files = differences(expected, actual['files'])
            packages = dependency_drift(root, actual['packages'])
            report['services'][service] = {
                'status': 'drift' if any(files.values()) or packages else 'matched',
                'source_files_checked': len(expected), 'files': files, 'dependencies': packages}
        except (subprocess.SubprocessError, OSError, ValueError, KeyError):
            # Do not expose raw Docker/command output: it can contain secrets.
            report['services'][service] = {'status': 'unavailable_or_invalid_response'}
    print(json.dumps(report, indent=2))
    return int(any(row['status'] != 'matched' for row in report['services'].values()))


if __name__ == '__main__':
    sys.exit(main())
