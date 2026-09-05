"""Read-only, account-wide Sleeper sync. League IDs are always discovered.

Parametrized per sport (settings.sleeper_sports) - Sleeper's own API already
generalizes cleanly across sports with an identical endpoint shape
(/state/{sport}, /user/{id}/leagues/{sport}/{season}, /players/{sport},
/league/{id}/matchups/{week}, /projections/{sport}/{season}/{week}), all
verified live 2026-09-04 for nba matching the nfl shape this module already
used. The SportsDataIO external-projections adapter
(src/data/providers/sportsdataio.py) stays NFL-only - its STAT_FIELDS
mapping is passing/rushing/receiving specific with no NBA equivalent, so it
is only ever called for sport == "nfl".
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.data.providers.sportsdataio import weekly_projections
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot, SleeperRoster

logger = logging.getLogger(__name__)


async def sync_sleeper_account(db: AsyncSession) -> dict[str, dict[str, int | str]]:
    settings = get_settings()
    if not settings.sleeper_username:
        raise ValueError("SLEEPER_USERNAME is not configured")
    username = settings.sleeper_username.lstrip("@")

    results: dict[str, dict[str, int | str]] = {}
    async with httpx.AsyncClient(base_url=settings.sleeper_base_url, timeout=20) as client:
        user = (await client.get(f"/user/{username}")).json()
        if not user.get("user_id"):
            raise ValueError("Sleeper username was not found")
        for sport in settings.sleeper_sports:
            # FOUND LIVE 2026-09-05: one sport's request failing (originally
            # NHL/MLB's /state response lacking league_season - see below)
            # raised out of the loop, and since this function commits once
            # at the end rather than per sport, that discarded every
            # already-fetched sport's data too - the real cause of "no
            # leagues synced" even though NFL leagues were being fetched
            # successfully every 15 minutes. A single sport's ingest should
            # never take down every other sport's, matching this app's own
            # "skip/park, don't raise" pattern for a single bad item
            # elsewhere (identity.py's resolve_player, lines.py's parked
            # props).
            try:
                results[sport] = await _sync_sport(db, client, user, sport)
            except Exception as exc:
                logger.warning("sleeper sync failed for sport=%s: %s", sport, exc)
                results[sport] = {"error": str(exc)}
        await db.commit()
    return results


async def _sync_sport(db: AsyncSession, client: httpx.AsyncClient, user: dict, sport: str) -> dict[str, int]:
    state = (await client.get(f"/state/{sport}")).json()
    # FOUND LIVE 2026-09-05: verified against the real endpoint - NFL and
    # NBA's /state response carries a league_season field, but MLB and
    # NHL's genuinely do not (both still carry season, which is identical
    # to league_season on the sports that have both). Not a transient gap -
    # both fields exist purely because Sleeper's fantasy-league "season"
    # can lag the real season for out-of-window sports; falling back to
    # season is correct rather than papering over a real absence.
    season = str(state.get("league_season") or state["season"])
    leagues = (await client.get(f"/user/{user['user_id']}/leagues/{sport}/{season}")).json()
    week = int(state.get("leg") or 1)

    player_catalog: dict | None = None
    external_projections = None
    if sport == "nfl":
        # A full catalog is also needed to safely map an external provider's
        # player names back to Sleeper IDs; no name-only database joins.
        if get_settings().sportsdataio_api_key:
            player_catalog = (await client.get(f"/players/{sport}")).json()
        external_projections = await weekly_projections(season, week, player_catalog or {})

    for league in leagues:
        league_id = league["league_id"]
        await _upsert_league(db, league, sport)
        rosters = (await client.get(f"/league/{league_id}/rosters")).json()
        await _upsert_rosters(db, league_id, rosters)
        metadata_exists = await db.scalar(
            select(SleeperLeagueSnapshot.league_id).where(
                SleeperLeagueSnapshot.league_id == league_id,
                SleeperLeagueSnapshot.kind == "player_metadata",
            ).limit(1)
        )
        if metadata_exists is None:
            if player_catalog is None:
                player_catalog = (await client.get(f"/players/{sport}")).json()
            rostered_ids = {str(player_id) for roster in rosters for player_id in (roster.get("players") or [])}
            await _snapshot(db, league_id, 0, "player_metadata", {
                player_id: player_catalog[player_id]
                for player_id in rostered_ids
                if player_id in player_catalog
            })
        matchups = (await client.get(f"/league/{league_id}/matchups/{week}")).json()
        transactions = (await client.get(f"/league/{league_id}/transactions/{week}")).json()
        await _snapshot(db, league_id, week, "matchups", matchups)
        await _snapshot(db, league_id, week, "transactions", transactions)
        await _snapshot(db, league_id, week, "account", user)
        projection_response = await client.get(
            f"/projections/{sport}/{season}/{week}", params={"season_type": state.get("season_type", "regular")}
        )
        projection_response.raise_for_status()
        await _snapshot(db, league_id, week, "projections", projection_response.json())
        if external_projections is not None:
            await _snapshot(db, league_id, week, "external_projections", external_projections)

    return {"leagues": len(leagues), "season": int(season), "week": week}


async def _upsert_league(db: AsyncSession, league: dict, sport: str) -> None:
    values = {"league_id": league["league_id"], "sport": sport, "name": league["name"], "season": league["season"], "status": league["status"], "roster_positions": league.get("roster_positions", []), "settings": league.get("settings", {}), "scoring_settings": league.get("scoring_settings", {}), "raw": league, "synced_at": datetime.now(timezone.utc)}
    await db.execute(insert(SleeperLeague).values(**values).on_conflict_do_update(index_elements=["league_id"], set_=values))


async def _upsert_rosters(db: AsyncSession, league_id: str, rosters: list[dict]) -> None:
    for roster in rosters:
        values = {"league_id": league_id, "roster_id": roster["roster_id"], "owner_id": roster.get("owner_id"), "starters": roster.get("starters") or [], "players": roster.get("players") or [], "settings": roster.get("settings") or {}, "synced_at": datetime.now(timezone.utc)}
        await db.execute(insert(SleeperRoster).values(**values).on_conflict_do_update(index_elements=["league_id", "roster_id"], set_=values))


async def _snapshot(db: AsyncSession, league_id: str, week: int, kind: str, payload: list | dict) -> None:
    values = {"league_id": league_id, "week": week, "kind": kind, "payload": payload, "synced_at": datetime.now(timezone.utc)}
    await db.execute(insert(SleeperLeagueSnapshot).values(**values).on_conflict_do_update(index_elements=["league_id", "week", "kind"], set_=values))
