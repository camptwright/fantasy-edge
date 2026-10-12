"""Ensure production dependency edits cannot silently bypass the runtime lock."""
from pathlib import Path
import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT=Path(__file__).resolve().parents[1]


def test_runtime_dependencies_are_exactly_pinned_and_compatible():
    locked={}
    for line in (ROOT/'requirements-runtime.lock').read_text().splitlines():
        if not line or line.startswith('#'):continue
        requirement=Requirement(line)
        pins=list(requirement.specifier)
        assert len(pins)==1 and pins[0].operator=='==' and '*' not in pins[0].version
        name=canonicalize_name(requirement.name)
        assert name not in locked
        locked[name]=pins[0].version
    project=tomllib.loads((ROOT/'pyproject.toml').read_text())
    for line in project['project']['dependencies']:
        dependency=Requirement(line)
        assert locked[canonicalize_name(dependency.name)] in dependency.specifier


def test_docker_install_enforces_lock_and_checks_transitive_dependencies():
    dockerfile=(ROOT/'Dockerfile').read_text()
    assert 'pip install -r requirements-runtime.lock' in dockerfile
    assert 'pip install -e . -c requirements-runtime.lock' in dockerfile
    assert 'pip check' in dockerfile
