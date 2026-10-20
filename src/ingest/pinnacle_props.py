"""Pinnacle player props from the guest API's "special" matchups (free).

`/leagues/{id}/matchups` lists each prop as a special: category "Player
Props", description "<player> Total <stat>", a `parent` game (home/away
team names and startTime) and Over/Under participants.
`/markets/straight` prices it as type "total" with one price per
participant (`points` the line). Verified live 2026-10-20: 450 NBA props
(points, rebounds, threes, assists, PRA), all two-way.

Same conservative binding as the other prop sources: the parent game must
match one scheduled game by both team names and kickoff, and the player an
exact unique sport/name (theodds_props.select_player). NBA only for now:
NFL Pinnacle props already arrive through ParlayAPI as `parlay_pinnacle`,
and a second copy would count Pinnacle twice in the prop board's consensus.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from config.settings import get_settings
from src.data.scrapers.base import ScraperError
from src.ingest.games import find_game_by_teams
from src.ingest.identity import resolve_team
from src.ingest.lines import record_prop_line
from src.ingest.pinnacle import PinnacleScraper, _auth_headers
from src.ingest.prop_events import event_binding
from src.ingest.runs import record_run
from src.ingest.theodds_props import select_player
from src.models.identity import Player

SOURCE = "pinnacle"
STATS = {"nba": {"Points": "points", "Rebounds": "rebounds", "Assists": "assists",
                 "Threes Made": "three_pointers_made", "Pts & Rebs & Asts": "points_rebounds_assists"}}


def stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def parse(matchups: list[dict], markets: list[dict], sport: str) -> list[dict]:
    """[{name, stat, line, over, under, home, away, kickoff}] for two-way, open, full-game props."""
    stats = STATS[sport]
    props = {}
    for m in matchups:
        special = m.get("special") or {}
        if special.get("category") != "Player Props":
            continue
        name, sep, stat = (special.get("description") or "").rpartition(" Total ")
        parent = m.get("parent") or {}
        teams = {p.get("alignment"): p.get("name") for p in parent.get("participants") or []}
        sides = {p.get("id"): str(p.get("name", "")).lower() for p in m.get("participants") or []}
        if not sep or stat not in stats or not teams.get("home") or not teams.get("away") or set(sides.values()) != {"over", "under"}:
            continue
        props[m["id"]] = {"name": name.strip(), "stat": stats[stat], "home": teams["home"], "away": teams["away"],
                          "kickoff": stamp(parent.get("startTime")), "sides": sides}
    out = []
    for market in markets:
        prop = props.get(market.get("matchupId"))
        if prop is None or market.get("type") != "total" or market.get("period") != 0 or market.get("status", "open") != "open":
            continue
        prices = {prop["sides"].get(p.get("participantId")): p for p in market.get("prices") or []}
        over, under = prices.get("over"), prices.get("under")
        if not over or not under or over.get("points") is None or over.get("points") != under.get("points"):
            continue
        out.append({**{k: v for k, v in prop.items() if k != "sides"}, "line": float(over["points"]),
                    "over": int(over["price"]), "under": int(under["price"])})
    return out


async def poll_props(db, sport: str = "nba", *, now: datetime | None = None, payload=None) -> dict:
    if sport not in STATS:
        return {"status": "unsupported_sport"}
    now = now or datetime.now(timezone.utc)
    settings = get_settings()
    league = settings.pinnacle_league_ids[sport]
    async with record_run(db, f"{SOURCE}_{sport}_props") as run:
        if payload is None:
            scraper = PinnacleScraper()
            try:
                matchups = await scraper.fetch_json(f"{settings.pinnacle_base_url}/leagues/{league}/matchups", headers=_auth_headers())
                markets = await scraper.fetch_json(f"{settings.pinnacle_base_url}/leagues/{league}/markets/straight", headers=_auth_headers())
            except ScraperError as exc:
                run.detail = str(exc)
                raise RuntimeError(str(exc)) from None
        else:
            matchups, markets = payload
        rows = parse(matchups, markets, sport)
        players = list((await db.scalars(select(Player).where(Player.sport == sport))).all())
        games, written, parked = {}, 0, 0
        for row in rows:
            key = (row["home"], row["away"], row["kickoff"])
            if key not in games:
                game = None
                if row["kickoff"] and now < row["kickoff"] <= now + timedelta(days=3):
                    try:
                        home = await resolve_team(db, row["home"], sport=sport)
                        away = await resolve_team(db, row["away"], sport=sport)
                        game = await find_game_by_teams(db, home_team_id=home.id, away_team_id=away.id, kickoff=row["kickoff"])
                    except LookupError:
                        game = None
                games[key] = game if game is not None and game.status == "scheduled" and game.game_time and game.game_time > now else None
            game = games[key]
            player = select_player(players, row["name"], game) if game else None
            if player is None:
                parked += 1
                continue
            if await record_prop_line(db, player_id=player.id, game_id=game.id, stat_type=row["stat"], line=row["line"],
                                      over_price_american=row["over"], under_price_american=row["under"],
                                      source=SOURCE, event_binding=event_binding(game)):
                written += 1
        await db.commit()
        run.rows_written = written
        result = {"parsed": len(rows), "written": written, "parked": parked}
        run.detail = str(result)
    return result
