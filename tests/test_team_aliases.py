"""Team alias crosswalk files (config/team_aliases/*.yaml) - structural
validation only. Correctness of resolve_team()'s DB-facing logic (the
ON CONFLICT-based create path, the espn_id-then-name lookup order) needs
real Postgres to exercise honestly - constraint #13/#16's own
expression-index lesson is that offline checks can't catch what only
Postgres itself will reject - so that half is smoke-tested against real
infrastructure per this repo's established practice (see CLAUDE.md's
Status section), not mocked here."""

from __future__ import annotations

from config.settings import get_team_aliases

EXPECTED_ALIAS_COUNTS = {"nfl": 32, "mlb": 30, "nhl": 32}


class TestTeamAliasFiles:
    def test_every_expected_sport_has_an_alias_file_that_loads(self):
        for sport in EXPECTED_ALIAS_COUNTS:
            aliases = get_team_aliases(sport)
            assert aliases, f"no aliases loaded for {sport}"

    def test_every_alias_entry_has_espn_name_and_espn_id(self):
        for sport in EXPECTED_ALIAS_COUNTS:
            for raw_name, alias in get_team_aliases(sport).items():
                assert alias.get("espn_name"), f"{sport}/{raw_name} missing espn_name"
                assert alias.get("espn_id"), f"{sport}/{raw_name} missing espn_id"

    def test_every_alias_key_is_a_real_string_not_a_yaml_coerced_type(self):
        # Regression test for a real bug found live against Postgres: an
        # unquoted "NO" (New Orleans) key parsed as the Python bool False
        # under PyYAML's YAML-1.1 safe_load, not the string "NO" - the
        # classic "Norway problem." A structural dict-shape check alone
        # doesn't catch this (the dict still has 32 entries with 32 unique
        # espn_ids); the SQL bind against a varchar column is what
        # actually rejected it. Guard the whole YAML-1.1 boolean literal
        # set here so a future team code (e.g. some sport's "ON", "TRUE")
        # can't reintroduce the same class of bug undetected.
        for sport in EXPECTED_ALIAS_COUNTS:
            for key in get_team_aliases(sport):
                assert isinstance(key, str), f"{sport} alias key {key!r} is {type(key).__name__}, not str"

    def test_nfl_has_all_32_current_teams(self):
        aliases = get_team_aliases("nfl")
        espn_ids = {a["espn_id"] for a in aliases.values()}
        assert len(espn_ids) == 32

    def test_mlb_has_all_30_current_teams(self):
        aliases = get_team_aliases("mlb")
        espn_ids = {a["espn_id"] for a in aliases.values()}
        assert len(espn_ids) == 30

    def test_nhl_has_all_32_current_teams(self):
        aliases = get_team_aliases("nhl")
        espn_ids = {a["espn_id"] for a in aliases.values()}
        assert len(espn_ids) == 32

    def test_unconfigured_sport_returns_empty_not_an_error(self):
        # nba/wnba deliberately have no crosswalk file - their historical
        # loader already emits ESPN-compatible full names.
        assert get_team_aliases("nba") == {}
        assert get_team_aliases("this-sport-does-not-exist") == {}

    def test_relocated_franchises_share_one_canonical_identity(self):
        # Arizona Coyotes -> Utah Mammoth: the same franchise must resolve
        # to the same espn_id under both its old and current NHL-API codes,
        # or the migration would create two Team rows for one real team.
        nhl = get_team_aliases("nhl")
        assert nhl["ARI"]["espn_id"] == nhl["UTA"]["espn_id"]

    def test_franchise_renames_share_one_canonical_identity(self):
        mlb = get_team_aliases("mlb")
        assert mlb["FLA"]["espn_id"] == mlb["MIA"]["espn_id"]
