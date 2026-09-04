"""Every config/team_aliases/*.yaml file, not just NFL's.

test_preserved.py's test_nfl_alias_keys_are_all_strings protects the one
preserved artifact from the NFL rebuild; this generalizes the same
constraint #24 tripwire ("NO" parses as the YAML-1.1 boolean False unless
quoted) to every sport's alias file, current and future, so a new sport's
file gets this safety net automatically rather than needing its own
hand-written copy of the same test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from config.settings import get_settings

ALIAS_DIR = Path(__file__).resolve().parents[1] / "config" / "team_aliases"


def _alias_files() -> list[Path]:
    return sorted(ALIAS_DIR.glob("*.yaml"))


def test_every_supported_sport_has_an_alias_file():
    existing = {path.stem for path in _alias_files()}
    for sport in get_settings().supported_sports:
        assert sport in existing, f"no config/team_aliases/{sport}.yaml"


@pytest.mark.parametrize("path", _alias_files(), ids=lambda p: p.stem)
def test_alias_keys_are_all_strings(path: Path):
    data = yaml.safe_load(path.read_text())
    aliases = data["aliases"]
    assert aliases, f"{path.name} has no entries"
    for key in aliases:
        assert isinstance(key, str), f"{path.name}: alias key {key!r} is {type(key)}, not str"


@pytest.mark.parametrize("path", _alias_files(), ids=lambda p: p.stem)
def test_alias_entries_carry_espn_name_and_id(path: Path):
    data = yaml.safe_load(path.read_text())
    for key, entry in data["aliases"].items():
        assert entry.get("espn_name"), f"{path.name}: {key!r} has no espn_name"
        assert entry.get("espn_id"), f"{path.name}: {key!r} has no espn_id"


@pytest.mark.parametrize("path", _alias_files(), ids=lambda p: p.stem)
def test_espn_ids_are_unique_within_one_sports_file(path: Path):
    """Duplicate espn_ids under one sport would let two different alias
    keys silently resolve to what identity.py's resolve_team() treats as
    the same team."""
    data = yaml.safe_load(path.read_text())
    espn_ids = [entry["espn_id"] for entry in data["aliases"].values()]
    duplicates = {espn_id for espn_id in espn_ids if espn_ids.count(espn_id) > 1}
    # NFL's file deliberately maps multiple abbreviations (relocation-era
    # franchises, WAS/WSH) onto the SAME espn_id - see identity.py's own
    # resolve_team() docstring. That's intentional there; this test only
    # protects sports that don't have that documented exception.
    if path.stem == "nfl":
        pytest.skip("nfl.yaml intentionally reuses espn_id across relocation-era abbreviations")
    assert not duplicates, f"{path.name}: espn_id(s) reused across keys: {duplicates}"
