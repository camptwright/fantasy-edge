"""Timestamped ESPN roster membership, exact provider IDs only; never a lineup."""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from config.settings import get_settings
from src.models.facts import Game
from src.models.identity import PlayerExternalId, Team

SUPPORTED = ("nfl", "ncaaf", "nba", "mlb")
PROVIDERS = {sport: "espn_" + sport for sport in SUPPORTED} | {"mlb": "mlb_stats_api"}
TTL = timedelta(hours=12)


def parse(payload, team, season):
    if str(payload.get("team", {}).get("id")) != str(team.espn_id):
        raise ValueError("roster team identity mismatch")
    if payload.get("season", {}).get("year") != season:
        raise ValueError("roster season mismatch")
    groups = payload.get("athletes")
    if not isinstance(groups, list) or not groups:
        raise ValueError("missing roster")
    athletes = []
    for group in groups:
        items = group.get("items") if "items" in group else [group]
        if not isinstance(items, list):
            raise ValueError("invalid roster group")
        for athlete in items:
            if not athlete.get("id"):
                raise ValueError("missing athlete id")
            athletes.append(str(athlete["id"]))
    if not athletes or len(athletes) != len(set(athletes)):
        raise ValueError("empty or duplicate roster identities")
    return sorted(athletes)


def parse_mlb(payload, provider_team_id):
    if str(payload.get("teamId")) != str(provider_team_id) or payload.get("rosterType") != "active":
        raise ValueError("MLB roster scope mismatch")
    ids = [str(r["person"]["id"]) for r in payload["roster"]]
    if not ids or len(ids) != len(set(ids)) or any(not value.isdigit() for value in ids):
        raise ValueError("empty, invalid or duplicate MLB roster")
    return sorted(ids)


async def collect(db):
    now = datetime.now(timezone.utc)
    games = (
        await db.scalars(
            select(Game).where(
                Game.sport.in_(SUPPORTED),
                Game.status == "scheduled",
                Game.game_time.isnot(None),
                Game.game_time > now,
                Game.game_time <= now + timedelta(days=7),
            )
        )
    ).all()
    seasons = {}
    for game in games:
        for team_id in (game.home_team_id, game.away_team_id):
            if team_id:
                seasons.setdefault(team_id, set()).add(game.season)
    teams = (await db.scalars(select(Team).where(Team.id.in_(seasons)))).all() if seasons else []
    limit = asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=20) as client:
        mlb_teams = {}
        if any(t.sport == "mlb" for t in teams):
            try:
                response = await client.get(
                    "https://statsapi.mlb.com/api/v1/teams", params={"sportId": 1}
                )
                response.raise_for_status()
                for team in response.json()["teams"]:
                    mlb_teams.setdefault(team["name"], []).append(team["id"])
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                pass  # MLB teams become unavailable; other sports still refresh.

        async def fetch(team):
            async with limit:
                url = (
                    f"{get_settings().espn_base_urls[team.sport]}/teams/{team.espn_id}/roster"
                    if team.sport != "mlb"
                    else "https://statsapi.mlb.com/api/v1/teams"
                )
                result = {
                    "team_id": str(team.id),
                    "sport": team.sport,
                    "provider": PROVIDERS[team.sport],
                    "url": url,
                    "status": "unavailable",
                }
                try:
                    if len(seasons[team.id]) != 1:
                        raise ValueError("ambiguous season")
                    season = next(iter(seasons[team.id]))
                    params = {}
                    if team.sport == "mlb":
                        candidates = mlb_teams.get(team.name, [])
                        if len(candidates) != 1:
                            raise ValueError("ambiguous MLB team identity")
                        url = f"https://statsapi.mlb.com/api/v1/teams/{candidates[0]}/roster"
                        params = {"rosterType": "active", "date": now.date().isoformat()}
                        result.update(
                            url=url, provider_team_id=str(candidates[0]), request_parameters=params
                        )
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    payload = response.json()
                    if team.sport == "mlb":
                        ids = parse_mlb(payload, candidates[0])
                    else:
                        ids = parse(payload, team, season)
                    result.update(
                        status="verified_roster",
                        athlete_ids=ids,
                        season=season,
                        observed_at=datetime.now(timezone.utc).isoformat(),
                        payload_sha256=hashlib.sha256(response.content).hexdigest(),
                        payload=payload,
                    )
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    result["error_type"] = type(exc).__name__
                    if isinstance(exc, ValueError):
                        result["detail"] = str(exc)[:200]
                return result

        rows = await asyncio.gather(*(fetch(team) for team in teams))
    return {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "teams": rows,
        "scope": "Scheduled games in next seven days; membership is not availability.",
    }


def load(directory, now):
    try:
        path = sorted(Path(directory).glob("*.json"))[-1]
        payload = json.loads(path.read_text())
        at = datetime.fromisoformat(payload["captured_at"])
        if payload.get("schema_version") != 1 or not timedelta(0) <= now - at <= TTL:
            return []
        # Only the latest complete attempt: never resurrect a failed team's old roster.
        return payload["teams"]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return []


async def contexts(db, players, games, directory, now):
    ids = {p.id for p in players}
    mappings = (
        (
            await db.scalars(
                select(PlayerExternalId).where(
                    PlayerExternalId.player_id.in_(ids),
                    PlayerExternalId.source.in_(list(PROVIDERS.values())),
                )
            )
        ).all()
        if ids
        else []
    )
    external = {}
    for row in mappings:
        external.setdefault(row.player_id, set()).add((row.source, row.external_id))
    rosters = load(directory, now)
    out = {}
    for player in players:
        matches = []
        for roster in rosters:
            try:
                if (
                    roster["sport"] == "mlb"
                    and roster.get("request_parameters", {}).get("rosterType") != "active"
                ):
                    continue
                age = now - datetime.fromisoformat(roster["observed_at"])
                if (
                    roster["status"] == "verified_roster"
                    and roster["sport"] == player.sport
                    and timedelta(0) <= age <= TTL
                ):
                    matched = sorted(
                        e
                        for source, e in external.get(player.id, set())
                        if source == roster["provider"] and e in roster["athlete_ids"]
                    )
                    if matched:
                        matches.append(
                            {
                                k: roster[k]
                                for k in (
                                    "team_id",
                                    "sport",
                                    "provider",
                                    "season",
                                    "observed_at",
                                    "payload_sha256",
                                    "url",
                                )
                            }
                            | {"athlete_ids": matched}
                        )
            except (KeyError, ValueError, TypeError):
                continue
        teams = {r["team_id"] for r in matches}
        out[str(player.id)] = (
            {**matches[0], "status": "corroborated"}
            if len(teams) == 1
            else {"status": "conflicting_rosters" if teams else "roster_unverified"}
        )
    return out


def reason(evidence, game, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        if evidence["status"] != "corroborated":
            return "player_roster_unverified"
        if not timedelta(0) <= now - datetime.fromisoformat(evidence["observed_at"]) <= TTL:
            return "player_roster_stale"
        if evidence["sport"] != game.sport or evidence["season"] != game.season:
            return "player_roster_scope_mismatch"
        if evidence["team_id"] not in (str(game.home_team_id), str(game.away_team_id)):
            return "player_game_team_mismatch"
        return None
    except (KeyError, ValueError, TypeError, AttributeError):
        return "player_roster_unverified"
