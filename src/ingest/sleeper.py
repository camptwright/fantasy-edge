"""Read-only, account-wide Sleeper sync. League IDs are always discovered.

Parametrized per sport (settings.sleeper_sports) - Sleeper's own API already
generalizes cleanly across sports with an identical endpoint shape
(/state/{sport}, /user/{id}/leagues/{sport}/{season}, /players/{sport},
/league/{id}/matchups/{week}, /projections/{sport}/{season}/{week}), all
verified live 2026-09-04 for nba matching the nfl shape this module already
used.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
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
    for league in leagues:
        league_id = league["league_id"]
        await _upsert_league(db, league, sport)
        rosters = (await client.get(f"/league/{league_id}/rosters")).json()
        # Best-effort team names for the trade recommender - Sleeper's own
        # roster objects carry no display name at all, only owner_id.
        # /league/{id}/users is a separate endpoint; a fetch failure here
        # degrades to "no team names" rather than failing the whole sync,
        # since nothing before this feature ever needed this data.
        team_names: dict[str, str] = {}
        try:
            users = (await client.get(f"/league/{league_id}/users")).json()
            for entry in users:
                if isinstance(entry, dict) and entry.get("user_id"):
                    metadata = entry.get("metadata") or {}
                    team_names[entry["user_id"]] = metadata.get("team_name") or entry.get("display_name") or entry["user_id"]
        except Exception as exc:
            logger.warning("sleeper users fetch failed for league_id=%s: %s", league_id, exc)
        await _upsert_rosters(db, league_id, rosters, team_names)
        metadata_exists = await db.scalar(
            select(SleeperLeagueSnapshot.league_id).where(
                SleeperLeagueSnapshot.league_id == league_id,
                SleeperLeagueSnapshot.kind == "player_metadata",
            ).limit(1)
        )
        if metadata_exists is None:
            if player_catalog is None:
                player_catalog = (await client.get(f"/players/{sport}")).json()
            # Widened from "rostered players only" to every fantasy-relevant
            # player: the projections payload's ID-keyed values carry no
            # name/position/team of their own (see projection_rows() in
            # src/api/main.py), so the waiver list - which by definition
            # covers players NOT on any roster - needs metadata for the
            # whole free-agent pool too, not just your own team. Trimmed to
            # the handful of fields actually used, since the untrimmed
            # catalog is ~14MB (Sleeper's own docs ask API consumers to
            # cache this endpoint at most once a day; this snapshot already
            # only (re)fetches when missing).
            relevant_positions = {"QB", "RB", "WR", "TE", "K", "DEF"} if sport == "nfl" else None
            await _snapshot(db, league_id, 0, "player_metadata", {
                player_id: {
                    "first_name": info.get("first_name"),
                    "last_name": info.get("last_name"),
                    "position": info.get("position"),
                    "team": info.get("team"),
                    "injury_status": info.get("injury_status"),
                }
                for player_id, info in player_catalog.items()
                if isinstance(info, dict) and (relevant_positions is None or info.get("position") in relevant_positions)
            })
        matchups = (await client.get(f"/league/{league_id}/matchups/{week}")).json()
        transactions = (await client.get(f"/league/{league_id}/transactions/{week}")).json()
        await _snapshot(db, league_id, week, "matchups", matchups)
        await _snapshot(db, league_id, week, "transactions", transactions)
        await _snapshot(db, league_id, week, "account", user)
        # season_type is a PATH segment here, not a query param - verified
        # live 2026-09-09: /projections/{sport}/{season}/{week}?season_type=X
        # returns 200 with every value an empty {} (confirmed for both the
        # current week and historically-completed weeks, i.e. it's not a
        # "too early in the season" gap - the query-param form simply
        # never returns real data). The real path is
        # /projections/{sport}/{season_type}/{season}/{week}, confirmed
        # live to return populated per-player stat projections.
        season_type = state.get("season_type", "regular")
        projection_response = await client.get(f"/projections/{sport}/{season_type}/{season}/{week}")
        projection_response.raise_for_status()
        await _snapshot(db, league_id, week, "projections", projection_response.json())
    return {"leagues": len(leagues), "season": int(season), "week": week}


async def _upsert_league(db: AsyncSession, league: dict, sport: str) -> None:
    values = {"league_id": league["league_id"], "sport": sport, "name": league["name"], "season": league["season"], "status": league["status"], "roster_positions": league.get("roster_positions", []), "settings": league.get("settings", {}), "scoring_settings": league.get("scoring_settings", {}), "raw": league, "synced_at": datetime.now(timezone.utc)}
    await db.execute(insert(SleeperLeague).values(**values).on_conflict_do_update(index_elements=["league_id"], set_=values))


async def _upsert_rosters(db: AsyncSession, league_id: str, rosters: list[dict], team_names: dict[str, str]) -> None:
    for roster in rosters:
        values = {"league_id": league_id, "roster_id": roster["roster_id"], "owner_id": roster.get("owner_id"), "team_name": team_names.get(roster.get("owner_id")), "starters": roster.get("starters") or [], "players": roster.get("players") or [], "settings": roster.get("settings") or {}, "synced_at": datetime.now(timezone.utc)}
        await db.execute(insert(SleeperRoster).values(**values).on_conflict_do_update(index_elements=["league_id", "roster_id"], set_=values))


async def _snapshot(db: AsyncSession, league_id: str, week: int, kind: str, payload: list | dict) -> None:
    values = {"league_id": league_id, "week": week, "kind": kind, "payload": payload, "synced_at": datetime.now(timezone.utc)}
    await db.execute(insert(SleeperLeagueSnapshot).values(**values).on_conflict_do_update(index_elements=["league_id", "week", "kind"], set_=values))
