"""Read-only ESPN Fantasy Football sync.

Unlike src/ingest/sleeper.py, this cannot discover leagues from an
account - ESPN's private-league API has no "list my leagues" call, only
per-league access gated behind two cookie values pulled from an
already-logged-in browser session (espn_s2, SWID). Every league to sync
must be listed explicitly in settings.espn_league_ids.

Normalizes into the SAME tables src/ingest/sleeper.py already writes
(SleeperLeague/SleeperRoster/SleeperLeagueSnapshot - see
alembic/versions/0014 and src/models/sleeper.py's docstring for why the
Sleeper-specific names stayed), so every existing endpoint in
src/api/main.py (leagues list, /analysis, /recommendations, /draft-score,
/matchup, /advice) works for an ESPN league with zero changes - none of
them do anything Sleeper-specific, they only ever treat league_id,
roster_positions, scoring_settings, and the "projections"/"player_
metadata"/"matchups"/"account" snapshot kinds as opaque, platform-
agnostic shapes.

Live-verified 2026-09-09 against a real 14-team league (roster/settings/
scoring/matchup/free-agent shapes, host, and two real response-shape
bugs - see PLAYER_POSITION_MAP's and _record_player's own comments for
what they were and how they were caught). Every field access still uses
.get() with a fallback, matching this codebase's existing defensive-
parsing style, so an assumption ESPN changes later (a new field shape,
a new position/team id) degrades instead of crashing the whole sync -
but that defensiveness is a safety net now, not a substitute for having
actually checked.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.ingest.espn_fantasy_constants import (
    ESPN_APPLIED_TOTAL_KEY,
    LINEUP_SLOT_MAP,
    PLAYER_POSITION_MAP,
    PRO_TEAM_MAP,
    STAT_ID_TO_KEY,
    SUPER_FLEX_SLOT_ID,
)
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot, SleeperRoster

logger = logging.getLogger(__name__)


def _normalize_swid(value: str) -> str:
    return value.strip().strip("{}").lower()


async def sync_espn_fantasy_account(db: AsyncSession) -> dict[str, dict[str, int | str]]:
    settings = get_settings()
    league_ids = [value.strip() for value in settings.espn_league_ids.split(",") if value.strip()]
    if not league_ids:
        raise ValueError("ESPN_LEAGUE_IDS is not configured")
    if not settings.espn_s2 or not settings.espn_swid:
        raise ValueError("ESPN_S2 and ESPN_SWID are not configured")
    my_swid = _normalize_swid(settings.espn_swid)

    results: dict[str, dict[str, int | str]] = {}
    cookies = {"espn_s2": settings.espn_s2, "SWID": settings.espn_swid}
    async with httpx.AsyncClient(base_url=settings.espn_fantasy_base_url, cookies=cookies, timeout=20) as client:
        for raw_league_id in league_ids:
            league_id = f"espn:{raw_league_id}"
            try:
                results[league_id] = await _sync_league(db, client, settings.espn_fantasy_season, raw_league_id, league_id, my_swid)
            except Exception as exc:
                # Same "one bad league must not discard every other
                # league's already-fetched data" reasoning as
                # sync_sleeper_account's per-sport try/except - this
                # function also commits once at the end.
                logger.warning("espn fantasy sync failed for league_id=%s: %s", league_id, exc)
                results[league_id] = {"error": str(exc)}
        await db.commit()
    return results


async def _sync_league(
    db: AsyncSession,
    client: httpx.AsyncClient,
    season: int,
    raw_league_id: str,
    league_id: str,
    my_swid: str,
) -> dict[str, int | str]:
    response = await client.get(
        f"/seasons/{season}/segments/0/leagues/{raw_league_id}",
        params=[("view", "mSettings"), ("view", "mRoster"), ("view", "mTeam"), ("view", "mMatchup"), ("view", "mMatchupScore")],
    )
    response.raise_for_status()
    payload = response.json()

    week = int(payload.get("scoringPeriodId") or payload.get("status", {}).get("currentMatchupPeriod") or 1)
    scoring_settings = _translate_scoring_settings(payload)
    roster_positions = _expand_roster_positions(payload)
    league_settings = payload.get("settings", {})
    await _upsert_league(db, league_id, raw_league_id, season, league_settings, roster_positions, scoring_settings, payload)

    teams = payload.get("teams", [])
    my_roster_id: int | None = None
    metadata: dict[str, dict] = {}
    projections: dict[str, dict] = {}
    team_starters: dict[int, list[str]] = {}
    for team in teams:
        team_id = team.get("id")
        owners = [_normalize_swid(str(owner)) for owner in team.get("owners", [])]
        if my_swid in owners:
            my_roster_id = team_id
        starters, players_on_team = _parse_roster_entries(team, metadata, projections, week)
        team_starters[team_id] = starters
        await _upsert_roster(db, league_id, team_id, team, starters, players_on_team)

    if my_roster_id is None:
        logger.warning("espn fantasy: no team in league_id=%s matched the configured SWID", league_id)
    free_agent_count = await _fetch_free_agents(client, raw_league_id, season, week, metadata, projections)
    await _snapshot(db, league_id, 0, "account", {"user_id": my_swid})
    await _snapshot(db, league_id, week, "player_metadata", metadata)
    await _snapshot(db, league_id, week, "projections", projections)
    await _snapshot(db, league_id, week, "matchups", _parse_matchups(payload, week, team_starters))
    return {"teams": len(teams), "free_agents": free_agent_count, "season": season, "week": week}


def _translate_scoring_settings(payload: dict) -> dict[str, float]:
    items = payload.get("settings", {}).get("scoringSettings", {}).get("scoringItems", [])
    scoring: dict[str, float] = {ESPN_APPLIED_TOTAL_KEY: 1.0}
    for item in items:
        key = STAT_ID_TO_KEY.get(item.get("statId"))
        if key is not None:
            scoring[key] = float(item.get("points") or 0)
    return scoring


def _expand_roster_positions(payload: dict) -> list[str]:
    slot_counts = payload.get("settings", {}).get("rosterSettings", {}).get("lineupSlotCounts", {})
    positions: list[str] = []
    for slot_id_str, count in slot_counts.items():
        slot_id = int(slot_id_str)
        if slot_id == SUPER_FLEX_SLOT_ID:
            token = "SUPER_FLEX"
        else:
            token = LINEUP_SLOT_MAP.get(slot_id)
        if token is None or not count:
            continue
        positions.extend([token] * int(count))
    return positions


def _record_player(player: dict, metadata: dict, projections: dict, week: int) -> str:
    """Write one ESPN player object's metadata + translated projection
    into the shared per-league dicts. Shared between rostered players
    (_parse_roster_entries, from the mRoster view's playerPoolEntry.player)
    and free agents (_fetch_free_agents, from kona_player_info's own
    top-level "player" key) - both carry the identical player object
    shape, confirmed live 2026-09-09 against a real league on both paths.
    """
    player_id = str(player.get("id"))
    position = PLAYER_POSITION_MAP.get(player.get("defaultPositionId"))
    metadata[player_id] = {
        "first_name": player.get("firstName"),
        "last_name": player.get("lastName") or player.get("fullName"),
        "position": position,
        "team": PRO_TEAM_MAP.get(player.get("proTeamId")),
        "injury_status": player.get("injuryStatus"),
    }
    # NOT {"stats": ...} - main.py's projection_rows() expects this dict's
    # VALUE to already be the flat stat dict itself (matching Sleeper's
    # own real /projections/{sport}/... shape, an ID-keyed object whose
    # values are flat), and treats a non-empty dict as "has real
    # projection data." Confirmed live 2026-09-09: wrapping this in an
    # extra "stats" key made every single player's translated points
    # read as 0.0 (view()'s stats.get(key) always missed since the real
    # key was nested one level deeper), the first live sync's most
    # visible bug.
    projections[player_id] = _translate_player_stats(player, position, week)
    return player_id


def _parse_roster_entries(team: dict, metadata: dict, projections: dict, week: int) -> tuple[list[str], list[str]]:
    starters: list[str] = []
    players_on_team: list[str] = []
    for entry in team.get("roster", {}).get("entries", []):
        player = entry.get("playerPoolEntry", {}).get("player", {})
        player_id = _record_player(player, metadata, projections, week)
        players_on_team.append(player_id)
        if entry.get("lineupSlotId") not in (20, 21):  # not bench, not IR
            starters.append(player_id)
    return starters, players_on_team


async def _fetch_free_agents(client: httpx.AsyncClient, raw_league_id: str, season: int, week: int, metadata: dict, projections: dict, limit: int = 300) -> int:
    """Fetch this league's free-agent/waiver pool and record it into the
    same metadata/projections dicts rostered players use - NOT into any
    team's players_on_team, so src/api/main.py's `owned` set (the union
    of every SleeperRoster row's players for this league) naturally
    excludes them, making them appear as real waiver candidates exactly
    the way an unrostered Sleeper player already does.

    ESPN has no per-league "list every player" endpoint - free agents
    are fetched via the kona_player_info view plus an x-fantasy-filter
    request header restricting to FREEAGENT/WAIVERS status, sorted by
    percent-owned descending (same shape/header the cwendt94/espn-api
    community package's own free_agents() uses). limit=300 (confirmed
    live 2026-09-09 to return that many in one request with no visible
    cap below the league's real 812-player pool) rather than every
    unowned player: a real waiver-worthy add is, by definition, going to
    carry meaningful ownership - the long tail past a few hundred spots
    down the ownership list has no realistic path to "beats your worst
    starter" and would only add parsing cost and DB row size for zero
    practical benefit.
    """
    filters = {"players": {
        "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
        "limit": limit,
        "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
        "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "STANDARD"},
    }}
    response = await client.get(
        f"/seasons/{season}/segments/0/leagues/{raw_league_id}",
        params={"view": "kona_player_info", "scoringPeriodId": week},
        headers={"x-fantasy-filter": json.dumps(filters)},
    )
    response.raise_for_status()
    items = response.json().get("players", [])
    for item in items:
        player = item.get("player", {})
        if player:
            _record_player(player, metadata, projections, week)
    return len(items)


def _translate_player_stats(player: dict, position: str | None, week: int) -> dict[str, float]:
    """Return the translated "stats" dict src/api/main.py's view() scores
    against league.scoring_settings.

    Always uses ESPN's own precomputed appliedTotal (via the single
    ESPN_APPLIED_TOTAL_KEY, weighted 1.0 in _translate_scoring_settings)
    rather than reconstructing a total from STAT_ID_TO_KEY - confirmed
    live 2026-09-09 against a real league's config: it carries 46 real
    scoringItems, many using position-scoped pointsOverrides (e.g.
    D/ST-only points-allowed brackets keyed by statId with the flat
    `points` field left at 0.0 and the real weight living in
    pointsOverrides['16']) that a flat statId->points mapping would
    silently read as zero. ESPN has already correctly applied every
    override for this exact player using the league's real settings;
    reconstructing that logic ourselves risks a silently wrong number
    for exactly the players/categories that make a league's rules
    non-default, which is the whole reason someone would need this
    integration in the first place.
    """
    projected = next(
        (row for row in player.get("stats", []) if row.get("statSourceId") == 1 and row.get("scoringPeriodId") == week),
        None,
    )
    if projected is None:
        return {}
    return {ESPN_APPLIED_TOTAL_KEY: float(projected.get("appliedTotal") or 0)}


def _parse_matchups(payload: dict, week: int, team_starters: dict[int, list[str]]) -> list[dict]:
    # ESPN's own schedule/matchup payload carries no per-side starters
    # list (side.rosterForMatchupPeriod is present but confirmed live
    # 2026-09-09 to sit empty until much closer to kickoff) - team_starters
    # (this week's real lineupSlotId-derived starters, already computed
    # once per team from the SAME response's mRoster view) is used
    # instead, keyed by the matching teamId, rather than a second request
    # for ESPN's own mBoxscore view.
    rows: list[dict] = []
    for matchup in payload.get("schedule", []):
        if matchup.get("matchupPeriodId") != week:
            continue
        for side_key in ("home", "away"):
            side = matchup.get(side_key)
            if not side:
                continue
            rows.append({
                "roster_id": side.get("teamId"),
                "matchup_id": matchup.get("matchupPeriodId"),
                "points": side.get("totalPoints", 0),
                "starters": team_starters.get(side.get("teamId"), []),
            })
    return rows


async def _upsert_league(
    db: AsyncSession,
    league_id: str,
    raw_league_id: str,
    season: int,
    league_settings: dict,
    roster_positions: list[str],
    scoring_settings: dict,
    raw: dict,
) -> None:
    values = {
        "league_id": league_id,
        "platform": "espn",
        "sport": "nfl",
        "name": league_settings.get("name") or f"ESPN League {raw_league_id}",
        "season": str(season),
        "status": "in_season",
        "roster_positions": roster_positions,
        "settings": {k: v for k, v in league_settings.items() if k not in ("scoringSettings", "rosterSettings")},
        "scoring_settings": scoring_settings,
        "raw": {"league_id": raw_league_id},  # full ESPN payload is large and roster-holding;
        # not archived wholesale the way Sleeper's already-small league
        # object is - the normalized snapshots below are the source of
        # truth for everything downstream actually reads.
        "synced_at": datetime.now(timezone.utc),
    }
    await db.execute(insert(SleeperLeague).values(**values).on_conflict_do_update(index_elements=["league_id"], set_=values))


async def _upsert_roster(db: AsyncSession, league_id: str, roster_id: int, team: dict, starters: list[str], players_on_team: list[str]) -> None:
    owners = team.get("owners", [])
    values = {
        "league_id": league_id,
        "roster_id": roster_id,
        "owner_id": _normalize_swid(str(owners[0])) if owners else None,
        "team_name": team.get("name"),
        "starters": starters,
        "players": players_on_team,
        "settings": {},
        "synced_at": datetime.now(timezone.utc),
    }
    await db.execute(insert(SleeperRoster).values(**values).on_conflict_do_update(index_elements=["league_id", "roster_id"], set_=values))


async def _snapshot(db: AsyncSession, league_id: str, week: int, kind: str, payload: list | dict) -> None:
    values = {"league_id": league_id, "week": week, "kind": kind, "payload": payload, "synced_at": datetime.now(timezone.utc)}
    await db.execute(insert(SleeperLeagueSnapshot).values(**values).on_conflict_do_update(index_elements=["league_id", "week", "kind"], set_=values))
