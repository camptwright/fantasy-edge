"""Strength of schedule by position (FantasyPros' SOS stars on waiver targets).

For every NFL defense and offensive position: average half-PPR fantasy points
allowed per game to that position this season (last season's games fill in
until a defense has four games), ranked 1-32 (1 = allows the most = easiest).
A team's schedule rating for a position averages its remaining opponents'
ranks over the rest of the season and the next four games, mapped to 1-5
stars (5 = easiest). Byes are skipped. Research context, not a projection.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from src.models.facts import Game
from src.models.governance import DerivedCheckpoint
from src.services.forecast_evidence import digest
from src.services.projection_engine import load_history, score

NAME = "schedule_strength:nfl"
POSITIONS = ("QB", "RB", "WR", "TE")
HALF_PPR = {"passing_yards": 0.04, "passing_touchdowns": 4, "passing_interceptions": -2, "rushing_yards": 0.1,
            "rushing_touchdowns": 6, "receptions": 0.5, "receiving_yards": 0.1, "receiving_touchdowns": 6,
            "fumbles_lost": -2}
REFRESH = timedelta(hours=6)
MIN_GAMES = 4


def allowed_ranks(history, season: int) -> dict:
    """{(defense team id, position): rank 1-32}, this season with last season as a fallback."""
    per_game = defaultdict(float)  # (defense, position, game) -> points allowed
    seasons = {}
    for p in history.players.values():
        pos = history.positions.get(p.player_id)
        g = history.games.get(p.game_id)
        if pos not in POSITIONS or g is None:
            continue
        defense = g.away_team_id if p.team_id == g.home_team_id else g.home_team_id
        per_game[(defense, pos, p.game_id)] += score(p.stats, HALF_PPR)
        seasons[p.game_id] = g.season
    totals = defaultdict(lambda: {"now": [], "before": []})
    for (defense, pos, gid), pts in per_game.items():
        totals[(defense, pos)]["now" if seasons[gid] == season else "before"].append(pts)
    averages = defaultdict(dict)
    for (defense, pos), v in totals.items():
        games = v["now"] if len(v["now"]) >= MIN_GAMES else (v["now"] + v["before"][-(MIN_GAMES * 2):])
        if games:
            averages[pos][defense] = sum(games) / len(games)
    ranks = {}
    for pos, by_defense in averages.items():
        for rank, (defense, _) in enumerate(sorted(by_defense.items(), key=lambda kv: -kv[1]), 1):
            ranks[(defense, pos)] = rank
    return ranks


def stars(avg_rank: float | None, teams: int = 32) -> int | None:
    """Absolute mapping of one average opponent rank (1 = easiest) to 1-5 stars."""
    if avg_rank is None:
        return None
    return max(1, min(5, round(1 + 4 * (teams - avg_rank) / (teams - 1))))


def relative_stars(values: dict) -> dict:
    """Quintiles across teams: the easiest fifth of schedules get 5 stars (lower average rank = easier)."""
    known = sorted((v, k) for k, v in values.items() if v is not None)
    out = {k: None for k in values}
    for i, (_, k) in enumerate(known):
        out[k] = 5 - min(4, i * 5 // len(known))
    return out


async def build(db, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    upcoming = (await db.scalars(select(Game).where(
        Game.sport == "nfl", Game.status == "scheduled", Game.game_time.is_not(None), Game.game_time > now,
        or_(Game.game_type.is_(None), Game.game_type == "REG")).order_by(Game.game_time))).all()
    if not upcoming:
        return {"status": "no_remaining_games"}
    season = min(g.season for g in upcoming)
    history = await load_history(db, [season - 1, season], now)
    ranks = allowed_ranks(history, season)
    schedule = defaultdict(list)
    for g in upcoming:
        if g.season == season and g.home_team_id and g.away_team_id:
            schedule[g.home_team_id].append(g.away_team_id)
            schedule[g.away_team_id].append(g.home_team_id)
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    teams = {str(t): {} for t in schedule}
    for pos in POSITIONS:
        ros = {t: mean([ranks[(o, pos)] for o in opp if (o, pos) in ranks]) for t, opp in schedule.items()}
        nxt = {t: mean([ranks[(o, pos)] for o in opp[:4] if (o, pos) in ranks]) for t, opp in schedule.items()}
        ros_stars, next_stars = relative_stars(ros), relative_stars(nxt)
        for t, opp in schedule.items():
            teams[str(t)][pos] = {"ros_stars": ros_stars[t], "next4_stars": next_stars[t], "games": len(opp),
                                  "avg_opponent_rank": round(ros[t], 1) if ros[t] is not None else None}
    return {"status": "research", "season": season, "generated_at": now.isoformat(), "teams": teams,
            "method": "half-PPR points allowed by position (rank 1 = most allowed); stars are quintiles of teams' "
                      "average opponent rank, 5 = easiest fifth of schedules"}


async def refresh(db, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    row = await db.get(DerivedCheckpoint, NAME)
    if row and now - datetime.fromisoformat(row.payload["generated_at"]) < REFRESH:
        return {"status": "fresh"}
    payload = await build(db, now=now)
    if payload.get("status") != "research":
        return payload
    values = {"name": NAME, "digest": digest(payload), "payload": payload, "updated_at": now}
    statement = insert(DerivedCheckpoint).values(**values)
    await db.execute(statement.on_conflict_do_update(
        index_elements=["name"], set_={k: getattr(statement.excluded, k) for k in values if k != "name"}))
    await db.commit()
    return {"status": "refreshed", "teams": len(payload["teams"])}


async def latest(db) -> dict | None:
    row = await db.get(DerivedCheckpoint, NAME)
    return row.payload if row and row.payload.get("status") == "research" else None
