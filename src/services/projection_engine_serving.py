"""Engine research projections for the fantasy workspace: this week through Week 18.

Runs the depth/status variant (projection_depth) over every remaining
scheduled regular-season game and stores the result in one derived
checkpoint for the fantasy snapshot builder to read. Nothing here is
prospectively qualified: `serving_promoted` is False and the workspace
labels every value as engine research beside the provider projection.

Game environment per game:
- `market_line`: the latest same-source spread and total (game_environment).
- `team_average_no_line`: no market exists yet (normally beyond next week).
  Each team's implied points are its mean over its last TEAM_LOOKBACK lined
  games (the league mean if it has none), spread the difference. Labeled,
  never presented as a market.

Availability: the nearest week per team uses every unavailable designation;
later weeks only the multi-game ones (IR, PUP, suspension, ...), because an
Out designation covers one game. Conditional on playing otherwise; no
injury-return or role-change modeling.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from src.models.facts import Game
from src.models.governance import DerivedCheckpoint
from src.services import projection_depth, team_model_serving
from src.services.engine_research import NAME, latest, player_points  # noqa: F401 (re-exported)
from src.services.forecast_evidence import digest
from src.services.game_environment import environments
from src.services.projection_engine import DEFAULT, TEAM_LOOKBACK, compute, load_history

RECIPE = "projection_engine_research_v1"


def fallback_environment(history_teams, team_id, league_mean: float) -> float:
    lined = sorted((t for t in history_teams if t.team_id == team_id and t.implied_points is not None),
                   key=lambda t: t.kickoff)[-TEAM_LOOKBACK:]
    return float(np.mean([t.implied_points for t in lined])) if lined else league_mean


async def build(db, *, now: datetime | None = None, catalog: dict | None = None) -> dict:
    from src.services.projection_engine_prospective import depth_version, latest_sleeper_catalog
    now = now or datetime.now(timezone.utc)
    synced_at = None
    if catalog is None:
        catalog, synced_at = await latest_sleeper_catalog(db)
    games = (await db.scalars(select(Game).where(
        Game.sport == "nfl", Game.status == "scheduled", Game.game_time.is_not(None), Game.game_time > now,
        or_(Game.game_type.is_(None), Game.game_type == "REG")))).all()
    if not games:
        return {"status": "no_remaining_games"}
    season = min(g.season for g in games)
    games = [g for g in games if g.season == season and g.home_team_id and g.away_team_id]
    history = await load_history(db, [season - 1, season], now)
    starters = projection_depth.last_starters(history, now)
    past = [t for t in history.teams.values() if t.kickoff < now]
    implied_all = [t.implied_points for t in past if t.implied_points is not None]
    league_mean = float(np.mean(implied_all)) if implied_all else 22.0
    env = await environments(db, [g.id for g in games], as_of=now)
    depth = await projection_depth.depth_inputs(db, catalog) if catalog else {}
    teams = await team_model_serving.state(db, now)

    nearest: dict[uuid.UUID, int] = {}
    for g in sorted(games, key=lambda g: g.game_time):
        for team in (g.home_team_id, g.away_team_id):
            nearest.setdefault(team, g.week)
    game_meta, players = {}, defaultdict(dict)
    removed_counts: dict[str, int] = defaultdict(int)
    for week in sorted({g.week for g in games}):
        week_games = [g for g in games if g.week == week]
        targets = []
        for g in week_games:
            if g.id in env:
                e = env[g.id]
                targets.append((g, e.home_points, e.away_points, e.home_spread))
                game_meta[str(g.id)] = {"week": week, "environment": "market_line", "source": e.source}
            else:
                home = fallback_environment(past, g.home_team_id, league_mean)
                away = fallback_environment(past, g.away_team_id, league_mean)
                projected = team_model_serving.project(teams, g, None) if teams else None
                if projected is not None and projected.get("home_points") is not None:
                    # Team scoring split: offense/defense total and the team model's margin.
                    home, away = projected["home_points"], projected["away_points"]
                elif projected is not None:
                    total, margin = home + away, projected["model_margin"]
                    home, away = total / 2 + margin / 2, total / 2 - margin / 2
                targets.append((g, home, away, away - home))
                game_meta[str(g.id)] = {"week": week, "source": None, "environment":
                                        "team_model_no_line" if projected is not None else "team_average_no_line"}
        base = compute(history, targets, now, DEFAULT)
        # Designation scope per team: this game is the team's nearest one or not.
        near = {pid: p for pid, p in base.items() if nearest.get(p.team_id) == week}
        later = {pid: p for pid, p in base.items() if nearest.get(p.team_id) != week}
        for subset, unavailable, vacating in ((near, projection_depth.UNAVAILABLE, projection_depth.VACATING),
                                              (later, projection_depth.LONG_TERM, set())):
            adjusted, removed = projection_depth.adjust(subset, depth, unavailable, vacating, starters)
            for reason in removed.values():
                removed_counts[reason] += 1
            for pid, p in adjusted.items():
                players[str(pid)][str(week)] = {
                    "game_id": str(p.game_id), "position": p.position,
                    "stats": {k: round(v, 3) for k, v in p.stats.items() if abs(v) >= 0.0005}}
    return {"status": "research", "recipe": RECIPE, "engine_version": depth_version(),
            "generated_at": now.isoformat(), "season": season,
            "depth_catalog_synced_at": synced_at.isoformat() if synced_at else None,
            "depth_status": ("applied" if any(isinstance(i, dict) and "depth_chart_order" in i for i in catalog.values())
                             else "team_and_status_only_no_depth_fields") if depth else "no_depth_catalog",
            "removed": dict(removed_counts), "games": game_meta, "players": dict(players),
            "conditional_on_playing": True, "serving_promoted": False}


async def refresh(db, *, now: datetime | None = None) -> dict:
    payload = await build(db, now=now)
    if payload.get("status") != "research":
        return payload
    values = {"name": NAME, "digest": digest(payload), "payload": payload,
              "updated_at": datetime.now(timezone.utc)}
    statement = insert(DerivedCheckpoint).values(**values)
    await db.execute(statement.on_conflict_do_update(
        index_elements=["name"], set_={k: getattr(statement.excluded, k) for k in values if k != "name"}))
    await db.commit()
    return {"status": "refreshed", "players": len(payload["players"]), "games": len(payload["games"]),
            "lined_games": sum(m["environment"] == "market_line" for m in payload["games"].values())}
