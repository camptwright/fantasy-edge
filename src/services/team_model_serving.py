"""Live state of the NFL team model v2 (src/services/team_model.py).

Starts from the fitted end-of-season ratings in config/nfl_team_model.json,
applies the offseason reversion, then replays every final NFL game after that
season from the database in kickoff order - the same walk-forward the offline
backtest ran. Closing lines: the archived nflverse close when present,
otherwise the last pregame Pinnacle spread, otherwise the median of the last
pregame spread across sources (None if nothing was captured).

Read-only; recomputed on demand (a season is a few hundred games).
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone

from sqlalchemy import or_, select

from src.models.facts import Game, TeamMarketLine
from src.models.identity import Team
from src.services import team_model


async def team_codes(db) -> dict:
    return {t.id: t.nflverse_abbr for t in (await db.scalars(select(Team).where(Team.sport == "nfl"))).all()}


async def market_spreads(db, games: list[Game]) -> dict:
    """Home expected margin per game from the best available pregame spread."""
    ids = [g.id for g in games]
    if not ids:
        return {}
    kickoff = {g.id: g.game_time for g in games}
    rows = (await db.scalars(select(TeamMarketLine).where(
        TeamMarketLine.game_id.in_(ids), TeamMarketLine.market == "spread", TeamMarketLine.side == "home",
        TeamMarketLine.line.is_not(None)))).all()
    best: dict = {}
    for r in rows:
        start = kickoff.get(r.game_id)
        closing = r.source == "nflverse" and r.line_type == "closing"
        if not closing and (start is None or r.observed_at >= start):
            continue  # constraint #2: no kickoff means no provable pregame quote
        latest = best.setdefault(r.game_id, {})
        key = "close" if closing else r.source
        if key not in latest or r.observed_at > latest[key].observed_at:
            latest[key] = r
    out = {}
    for game_id, by_source in best.items():
        pick = by_source.get("close") or by_source.get("pinnacle")
        out[game_id] = -pick.line if pick else -statistics.median(r.line for r in by_source.values())
    return out


async def state(db, now: datetime | None = None) -> dict | None:
    artifact = team_model.load()
    if artifact is None:
        return None
    now = now or datetime.now(timezone.utc)
    p = artifact["params"]
    codes = await team_codes(db)
    through = artifact["ratings_through_season"]
    games = (await db.scalars(select(Game).where(
        Game.sport == "nfl", Game.season > through, Game.status == "final", Game.home_score.is_not(None),
        Game.away_score.is_not(None), Game.game_time.is_not(None), Game.game_time <= now,
        or_(Game.game_type.is_(None), Game.game_type != "PRE")).order_by(Game.game_time))).all()
    spreads = await market_spreads(db, games)
    ratings = dict(artifact["ratings"])
    season, last_played, replayed = through, {}, 0
    for g in games:
        home, away = codes.get(g.home_team_id), codes.get(g.away_team_id)
        if home is None or away is None:
            continue
        if g.season != season:
            ratings, season = team_model.rollover(p, ratings), g.season
        rest = rest_difference(last_played, home, away, g.game_time)
        expected = team_model.expected_margin(p, ratings.get(home, 0.0), ratings.get(away, 0.0), rest_diff=rest)
        ratings[home], ratings[away] = team_model.update(p, ratings.get(home, 0.0), ratings.get(away, 0.0), expected,
                                                         g.home_score - g.away_score, spreads.get(g.id))
        last_played[home] = last_played[away] = g.game_time
        replayed += 1
    current_season = season if replayed else through + 1
    if current_season > season:
        ratings = team_model.rollover(p, ratings)  # preseason: reversion not yet applied by a replayed game
    return {"recipe": artifact["version"], "params": p, "ratings": ratings, "last_played": last_played,
            "codes": codes, "replayed_games": replayed, "season": current_season, "evidence": artifact["evidence"]}


def rest_difference(last_played: dict, home: str, away: str, kickoff: datetime) -> float:
    """Home minus away days since each team's last game; 0 when either is unknown (season openers)."""
    if home not in last_played or away not in last_played:
        return 0.0
    return ((kickoff - last_played[home]) - (kickoff - last_played[away])).total_seconds() / 86400


def project(s: dict, game: Game, market_margin: float | None) -> dict | None:
    """Model and market-regressed home margin and probabilities for one upcoming game."""
    home, away = s["codes"].get(game.home_team_id), s["codes"].get(game.away_team_id)
    if home not in s["ratings"] or away not in s["ratings"]:
        return None
    p = s["params"]
    rest = rest_difference(s["last_played"], home, away, game.game_time) if game.game_time else 0.0
    model = team_model.expected_margin(p, s["ratings"][home], s["ratings"][away], rest_diff=rest)
    final = team_model.regress_to_market(p, model, market_margin)
    return {"home": home, "away": away, "model_margin": round(model, 2), "market_margin": market_margin,
            "margin": round(final, 2), "home_win_probability": round(team_model.win_probability(p, final), 4),
            "market_weight": None if market_margin is None else round(team_model.market_weight(p, model, market_margin), 3)}
