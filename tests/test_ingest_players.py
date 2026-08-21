"""Player identity and long-form statistics.

The Josh Allen case is the reason this crosswalk exists as a real table: two
active players share that name (a Jacksonville edge rusher and the Buffalo
quarterback). A name-based join attributes one player's props to the other's
statistics and raises nothing.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from src.ingest.identity import resolve_player
from src.ingest.players import ingest_player_stats, ingest_players
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player, PlayerExternalId


async def test_both_josh_allens_are_distinct_players(db):
    await ingest_players(db)
    rows = await db.execute(select(Player).where(Player.full_name.ilike("josh allen")))
    allens = list(rows.scalars())
    assert len(allens) >= 2, "expected at least two distinct players named Josh Allen"
    assert len({p.gsis_id for p in allens}) == len(allens), "gsis_id collision"


async def test_resolve_player_returns_none_rather_than_guessing(db):
    await ingest_players(db)
    result = await resolve_player(
        db, source="underdog", external_id="unknown-uuid", full_name="Nobody Here"
    )
    assert result is None, "unresolvable identifiers must be parked, never guessed"


async def test_resolve_player_returns_none_for_ambiguous_name(db):
    """The Josh Allen case: a Jacksonville edge rusher and the Buffalo
    quarterback share this exact name. resolve_player must never guess -
    a wrong match silently poisons training data with no error anywhere."""
    await ingest_players(db)
    result = await resolve_player(
        db, source="some_new_source", external_id="unused-id", full_name="Josh Allen"
    )
    assert result is None, "an ambiguous name must resolve to None, never a guess"


async def test_resolve_player_is_stable_across_calls(db):
    await ingest_players(db)
    known = await db.scalar(select(Player).where(Player.gsis_id.isnot(None)).limit(1))
    first = await resolve_player(
        db, source="espn", external_id="espn-123", full_name=known.full_name
    )
    second = await resolve_player(
        db, source="espn", external_id="espn-123", full_name=known.full_name
    )
    assert first is not None and first.id == second.id

    mappings = await db.scalar(
        select(func.count())
        .select_from(PlayerExternalId)
        .where(PlayerExternalId.source == "espn", PlayerExternalId.external_id == "espn-123")
    )
    assert mappings == 1, "resolve_player wrote a duplicate crosswalk row"


async def test_player_stats_are_long_form_and_normalized(db):
    await ingest_players(db)
    written = await ingest_player_stats(db, seasons=[2025])
    assert written > 0

    stat_types = await db.execute(select(PlayerGameStat.stat_type).distinct())
    values = {row[0] for row in stat_types}
    assert values, "no statistics ingested"
    # CONSTRAINT #8: normalized at ingest, so cross-source joins line up.
    assert all(value == value.lower() and " " not in value for value in values)


async def test_stats_attach_to_a_game_the_players_team_actually_played(db):
    """Season and week alone match ~16 games. Without the team, every
    player's statistics would attach to an arbitrary game that week - a
    corruption that produces no error and no obviously wrong row.

    NOTE: `current_team_id` is never populated by `ingest_players()`, so a
    bare `player.current_team_id in (None, home, away)` check is vacuous -
    it passes even if `_game_for()` ignored the team entirely, since every
    player's `current_team_id` is always `None`. The real assertion below
    pins a specific, independently-known 2025 week-1 matchup (Chiefs at
    Chargers, nflverse game_id "2025_01_KC_LAC") and a player from one of
    those two teams (Patrick Mahomes, gsis_id "00-0033873", Chiefs QB), and
    checks his stat rows attach to THAT game and no other - not "one of
    sixteen possible week-1 games", the literal correct one.
    """
    await ingest_players(db)
    await ingest_player_stats(db, seasons=[2025])

    kc_lac = await db.scalar(
        select(Game).where(Game.nflverse_game_id == "2025_01_KC_LAC")
    )
    assert kc_lac is not None, "the real 2025 week-1 KC@LAC game must have been ingested"

    # A different, unrelated week-1 game - the "wrong" match season+week
    # alone would be unable to rule out.
    dal_phi = await db.scalar(
        select(Game).where(Game.nflverse_game_id == "2025_01_DAL_PHI")
    )
    assert dal_phi is not None, "the real 2025 week-1 DAL@PHI game must have been ingested"
    assert dal_phi.id != kc_lac.id

    mahomes = await db.scalar(select(Player).where(Player.gsis_id == "00-0033873"))
    assert mahomes is not None, "Patrick Mahomes must have been ingested"

    # Mahomes' week-1 stats must attach to the game the Chiefs actually
    # played (KC@LAC), not merely "a" week-1 game.
    mahomes_kc_lac_stats = await db.scalar(
        select(func.count())
        .select_from(PlayerGameStat)
        .where(PlayerGameStat.player_id == mahomes.id, PlayerGameStat.game_id == kc_lac.id)
    )
    assert mahomes_kc_lac_stats > 0, "Mahomes has no stats attached to the real KC@LAC game"

    # And they must NOT have leaked into an unrelated week-1 game his team
    # never played - the exact corruption season+week-only matching risks.
    mahomes_dal_phi_stats = await db.scalar(
        select(func.count())
        .select_from(PlayerGameStat)
        .where(PlayerGameStat.player_id == mahomes.id, PlayerGameStat.game_id == dal_phi.id)
    )
    assert mahomes_dal_phi_stats == 0, (
        "Mahomes' stats leaked into DAL@PHI, a week-1 game the Chiefs never played"
    )

    # Still exercise the general property across a broader sample: every
    # joined row's game has two real teams (not the disambiguation itself,
    # but a sanity check that the join is well-formed).
    rows = await db.execute(
        select(PlayerGameStat, Game, Player)
        .join(Game, PlayerGameStat.game_id == Game.id)
        .join(Player, PlayerGameStat.player_id == Player.id)
        .limit(200)
    )
    checked = 0
    for stat, game, player in rows:
        assert game.home_team_id is not None and game.away_team_id is not None
        checked += 1
    assert checked > 0, "no joined rows to verify"


async def test_player_stat_uniqueness_is_enforced_by_the_database(db):
    await ingest_players(db)
    await ingest_player_stats(db, seasons=[2025])
    row = await db.scalar(select(PlayerGameStat).limit(1))
    db.add(
        PlayerGameStat(
            player_id=row.player_id,
            game_id=row.game_id,
            stat_type=row.stat_type,
            value=row.value,
        )
    )
    with pytest.raises(Exception):
        await db.flush()
    await db.rollback()
