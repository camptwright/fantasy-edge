"""The five preserved artifacts must survive the clean slate intact.

Each encodes either a production incident or a fact verified against a live
source. This test is the tripwire that catches an over-eager deletion.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_preserved_files_exist():
    for relative in [
        "src/utils/odds_math.py",
        "src/utils/normalize.py",
        "src/data/providers/underdog_api.py",
        "config/team_aliases/nfl.yaml",
        "CLAUDE.md",
    ]:
        assert (ROOT / relative).is_file(), f"preserved file missing: {relative}"


def test_odds_math_still_imports_and_computes():
    from src.utils.odds_math import remove_vig_two_way

    fair_home, fair_away = remove_vig_two_way(-110, -110)
    assert fair_home == pytest.approx(0.5, abs=1e-9)
    assert fair_away == pytest.approx(0.5, abs=1e-9)


def test_nfl_alias_keys_are_all_strings():
    """Constraint #24: an unquoted NO parses as the boolean False under
    PyYAML's YAML 1.1 safe_load - the 'Norway problem' - and silently
    corrupts New Orleans' identity.

    The file has 37 entries: 32 real NFL teams, Washington Commanders has two
    entries (WAS, WSH), and three relocated franchises each carry one extra
    pre-move nflverse abbreviation (Rams: LA + STL, Chargers: LAC + SD,
    Raiders: LV + OAK) - all under a top-level `aliases:` key. Task 3 added
    the four relocation-era entries after discovering live (2026-08-20, via
    nflreadpy.load_schedules across 1999-2025) that nflverse's schedules
    table emits LA/STL/SD/OAK and the file did not cover them, which made
    resolve_team() raise LookupError the moment ingestion reached any of
    those franchises' games. Iterating the outer document itself would
    trivially pass with one string key ("aliases") and never touch the real
    data this test exists to protect.
    """
    import yaml

    data = yaml.safe_load((ROOT / "config/team_aliases/nfl.yaml").read_text())
    aliases = data["aliases"]
    assert len(aliases) == 37, f"expected 37 NFL team aliases, got {len(aliases)}"
    for key in aliases:
        assert isinstance(key, str), f"alias key {key!r} is {type(key)}, not str"


def test_underdog_provider_still_imports():
    """A file-existence check alone does not prove a module is importable.
    underdog_api.py originally depended on src/data/providers/base.py and
    src/utils/logging.py, both deleted by this task - an import-only test
    is what would have caught that before it shipped."""
    from src.data.providers.underdog_api import get_over_under_lines, raw_lines_to_props

    assert callable(get_over_under_lines)
    assert callable(raw_lines_to_props)
