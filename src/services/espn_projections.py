"""ESPN's weekly stat-level projections: a second independent source.

FantasyPros' consensus method (and independent studies of it) shows an
average of independent projection sources beats nearly every single source.
Sleeper's projections are licensed from RotoWire; ESPN's come from its own
analysts. This module:

- fetches ESPN's projected stats (statSourceId 1) for QB/RB/WR/TE through
  the already-configured ESPN league read API, translated to Sleeper scoring
  keys so any league's rules can score them;
- freezes them prospectively once per (game, player) inside the same 72-hour
  pregame window the engine uses (create-only, first capture wins), for
  grading against Sleeper in projection_engine_prospective.report;
- keeps the latest fetch as a checkpoint for display.

Research only: nothing here changes decisions or the versioned prediction.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from config.settings import get_settings
from src.models.facts import Game
from src.models.governance import DerivedCheckpoint
from src.ingest.espn_fantasy_constants import PRO_TEAM_MAP
from src.services.forecast_evidence import digest
from src.services.player_identity import resolve_platform_players
from src.services.roster_stat_prospective import publish

NAME = "espn_projections:latest"
POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE"}
# ESPN projected stat ids -> Sleeper scoring keys. 61 duplicates 42 and 41
# duplicates 53 in ESPN's payload, so only one of each is read.
STAT_KEYS = {"3": "pass_yd", "4": "pass_td", "19": "pass_2pt", "20": "pass_int", "24": "rush_yd", "25": "rush_td",
             "26": "rush_2pt", "53": "rec", "42": "rec_yd", "43": "rec_td", "44": "rec_2pt", "72": "fum_lost"}
TEAM_ALIASES = {"WSH": "WAS"}  # ESPN code -> nflverse code
CAPTURE_WINDOW = timedelta(hours=72)
REFRESH = timedelta(hours=3)  # one ESPN request per refresh, at most


def translate(espn_player: dict, week: int) -> dict | None:
    proj = next((x for x in espn_player.get("stats", [])
                 if x.get("statSourceId") == 1 and x.get("scoringPeriodId") == week), None)
    stats = (proj or {}).get("stats") or {}
    if not stats:
        return None
    return {key: round(float(stats[i]), 4) for i, key in STAT_KEYS.items() if i in stats}


async def fetch(season: int, week: int, limit: int = 1000) -> dict[str, dict]:
    """{espn player id: {sleeper key: projected value}} for one week."""
    s = get_settings()
    league = next((x.strip() for x in s.espn_league_ids.split(",") if x.strip()), None)
    if league is None:
        raise ValueError("no ESPN league configured")
    cookies = {"espn_s2": s.espn_s2, "SWID": s.espn_swid} if s.espn_s2 else None
    f = {"players": {"limit": limit, "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                     "filterSlotIds": {"value": [0, 2, 4, 6]}}}
    async with httpx.AsyncClient(base_url=s.espn_fantasy_base_url, cookies=cookies, timeout=60) as client:
        r = await client.get(f"/seasons/{season}/segments/0/leagues/{league}",
                             params={"view": "kona_player_info", "scoringPeriodId": week},
                             headers={"x-fantasy-filter": json.dumps(f)})
        r.raise_for_status()
    out = {}
    for item in r.json().get("players", []):
        p = item.get("player", {})
        if p.get("defaultPositionId") in POSITIONS:
            stats = translate(p, week)
            if stats:
                team = PRO_TEAM_MAP.get(p.get("proTeamId"))
                out[str(p["id"])] = {"position": POSITIONS[p["defaultPositionId"]], "stats": stats,
                                     "team": TEAM_ALIASES.get(team, team)}
    return out


def score(stats: dict, weights: dict) -> float:
    """League points from Sleeper-keyed stats (weights from offensive_weights)."""
    return sum(float(stats.get(k, 0.0)) * w for k, w in weights.items())


def archive_root():
    from src.services.projection_engine_prospective import archive_root as engine_root
    return engine_root() / "espn"


async def capture(db, *, now: datetime | None = None, fetcher=fetch) -> dict:
    """Freeze ESPN projections for players whose game kicks off within the window; refresh the display checkpoint."""
    now = now or datetime.now(timezone.utc)
    games = (await db.scalars(select(Game).where(
        Game.sport == "nfl", Game.status == "scheduled", Game.game_time.is_not(None),
        Game.game_time > now + timedelta(minutes=5), Game.game_time <= now + CAPTURE_WINDOW))).all()
    upcoming = (await db.scalars(select(Game).where(
        Game.sport == "nfl", Game.status == "scheduled", Game.game_time.is_not(None), Game.game_time > now)
        .order_by(Game.game_time).limit(1))).first()
    week_games = games or ([upcoming] if upcoming else [])
    if not week_games or week_games[0].week is None:
        return {"status": "no_upcoming_week", "captured": 0}
    season, week = week_games[0].season, week_games[0].week
    previous = await latest(db)
    if (previous and previous.get("week") == week and previous.get("season") == season
            and now - datetime.fromisoformat(previous["fetched_at"]) < REFRESH):
        return {"status": "fresh", "week": week, "captured": 0}
    try:
        raw = await fetcher(season, week)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {"status": "espn_unavailable", "error": type(exc).__name__, "captured": 0}
    resolved = await resolve_platform_players(db, "espn", sorted(raw))
    rows = {str(resolved[i].id): {"espn_id": i, **v} for i, v in raw.items() if resolved.get(i)}
    payload = {"season": season, "week": week, "fetched_at": now.isoformat(), "players": rows}
    values = {"name": NAME, "digest": digest(payload), "payload": payload, "updated_at": now}
    statement = insert(DerivedCheckpoint).values(**values)
    await db.execute(statement.on_conflict_do_update(
        index_elements=["name"], set_={k: getattr(statement.excluded, k) for k in values if k != "name"}))
    await db.commit()
    # The player's team comes from ESPN's own proTeamId (canonical players
    # carry no reliable current team), matched to the game by team code.
    from src.services.team_model_serving import team_codes
    codes = await team_codes(db)
    team_game = {}
    for g in games:
        for team in (g.home_team_id, g.away_team_id):
            if codes.get(team):
                team_game[codes[team]] = g
    written = 0
    for pid, row in rows.items():
        game = team_game.get(row.get("team"))
        if game is None or game.week != week:
            continue
        rid = hashlib.sha256(f"espn:{game.id}:{pid}".encode()).hexdigest()
        written += bool(publish(archive_root() / "forecasts" / f"{rid}.json", {
            "id": rid, "source": "espn", "captured_at": now.isoformat(), "game_id": str(game.id),
            "season": season, "week": week, "kickoff": game.game_time.isoformat(), "player_id": pid,
            "espn_id": row["espn_id"], "team": row["team"], "position": row["position"], "stats": row["stats"]}))
    return {"status": "captured", "season": season, "week": week, "fetched": len(raw), "resolved": len(rows),
            "captured": written}


def frozen(root=None) -> dict[tuple[str, str], dict]:
    """(game_id, canonical player id) -> frozen pregame ESPN record."""
    root = root or archive_root()
    out = {}
    for path in sorted((root / "forecasts").glob("*.json")):
        r = json.loads(path.read_text())
        if datetime.fromisoformat(r["captured_at"]) < datetime.fromisoformat(r["kickoff"]):
            out[(r["game_id"], r["player_id"])] = r
    return out


async def latest(db) -> dict | None:
    row = await db.get(DerivedCheckpoint, NAME)
    return row.payload if row else None
