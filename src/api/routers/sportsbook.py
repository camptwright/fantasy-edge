"""The sportsbook API surface homelab-dashboard's Fantasy tile already
expects (src/tiles/fantasy/client.ts there, "verified against the real
deployed API" 2026-08-03, before this repo's NFL rebuild removed it).

This was never part of the rebuild's own written plan - Plan 2 (model, API,
parlays) was deferred and never authored (see
docs/superpowers/specs/2026-08-20-fantasy-edge-nfl-rebuild-design.md in
homelab-master). Built here against the existing data-foundation schema
(team_market_lines, player_prop_lines, games) plus the new Elo baseline in
src/services/elo.py, shaped to match the dashboard client's documented
PropLine/Signal interfaces field-for-field.

Constraint #7 (CLAUDE.md): every list endpoint here uses PostgreSQL
DISTINCT ON to return only the latest observation per identity key - the
same discipline props_agent/props ingestion already enforces at write time,
now enforced again at read time so duplicate/stale rows never reach a
client.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.db.client import get_db
from src.models.facts import Game, PlayerPropLine, TeamMarketLine
from src.models.governance import CalibrationReport, RecommendationSnapshot
from src.models.identity import Player, Team
from src.models.ratings import TeamRating
from src.services.elo import moneyline_probability, spread_cover_probability
from src.services.projections import MIN_GAMES_FOR_PROJECTION, over_probability, project_stats
from src.services.totals import expected_total_points, is_qualified, total_over_probability
from src.utils.normalize import normalize_player_name
from src.utils.odds_math import (
    american_to_decimal,
    american_to_implied,
    decimal_to_american,
    expected_value_percent,
    remove_vig_two_way,
)

router = APIRouter()

# Every market this baseline can honestly speak to: moneyline/spread from
# the Elo rating (src/services/elo.py), total from the scoring-average
# baseline (src/services/totals.py) that same rating update maintains.
_MODELED_MARKETS = ("moneyline", "spread", "total")


async def _team_lookup(db: AsyncSession, team_ids: set[uuid.UUID]) -> dict[uuid.UUID, Team]:
    if not team_ids:
        return {}
    rows = (await db.execute(select(Team).where(Team.id.in_(team_ids)))).scalars()
    return {team.id: team for team in rows}


async def _rating_lookup(db: AsyncSession, team_ids: set[uuid.UUID]) -> dict[uuid.UUID, TeamRating]:
    if not team_ids:
        return {}
    rows = (
        await db.execute(select(TeamRating).where(TeamRating.team_id.in_(team_ids)))
    ).scalars()
    return {rating.team_id: rating for rating in rows}


def _emit_pair_rows(
    out: list[dict[str, Any]],
    pairs: tuple[tuple[TeamMarketLine, float, str, float | None], ...],
    *,
    market: str,
    source: str,
    matchup: str,
    game: Game,
) -> None:
    """Shared row-builder for both sides of one (game, market, source)
    quote - moneyline/spread (home/away) and total (over/under) all end up
    here with an identical output shape, just different `pairs` inputs."""
    for line, model_prob, selection, fair_prob in pairs:
        implied_prob = american_to_implied(line.price_american) if line.price_american is not None else None
        ev_percent = (
            expected_value_percent(model_prob, line.price_american)
            if line.price_american is not None
            else None
        )
        kelly = None
        if line.price_american is not None:
            b = american_to_decimal(line.price_american) - 1.0
            edge = model_prob * (b + 1.0) - 1.0
            full_kelly = max(0.0, edge / b) if b > 0 else 0.0
            kelly = round(full_kelly * get_settings().kelly_fraction_cap, 4)

        out.append(
            {
                "id": str(line.id),
                "sport": game.sport,
                "market": market,
                "selection": selection,
                "bookmaker": source,
                "price_american": line.price_american,
                "model_probability": round(model_prob, 4),
                "fair_probability": round(fair_prob, 4) if fair_prob is not None else None,
                "implied_probability": round(implied_prob, 4) if implied_prob is not None else None,
                "ev_percent": round(ev_percent, 2) if ev_percent is not None else 0.0,
                "kelly_fraction": kelly,
                # No credit/staking system yet (deferred contest system) -
                # null rather than an invented unit size.
                "stake_units": None,
                "confidence": None,
                "tier": None,
                # No settlement/grading system yet (same deferral) - null
                # until a real contest engine can grade this leg.
                "result": None,
                "created_at": line.observed_at.isoformat(),
                "matchup": matchup,
                "game_time": game.game_time.isoformat() if game.game_time else None,
                "game_status": game.status,
            }
        )


async def prop_rows(db: AsyncSession, sport: str | None) -> list[dict[str, Any]]:
    stmt = select(PlayerPropLine, Player).join(Player, PlayerPropLine.player_id == Player.id)
    if sport is not None:
        stmt = stmt.where(Player.sport == sport)
    stmt = stmt.distinct(
        PlayerPropLine.player_id, PlayerPropLine.stat_type, PlayerPropLine.source
    ).order_by(
        PlayerPropLine.player_id,
        PlayerPropLine.stat_type,
        PlayerPropLine.source,
        PlayerPropLine.observed_at.desc(),
    )
    rows = (await db.execute(stmt)).all()

    team_ids = {row.Player.current_team_id for row in rows if row.Player.current_team_id}
    teams = await _team_lookup(db, team_ids)
    projections = await project_stats(db, {(player.id, prop.stat_type) for prop, player in rows})

    out = []
    for prop, player in rows:
        projected = projections.get((player.id, prop.stat_type))
        projection_value = projected[0] if projected is not None else None
        model_probability = None
        under_model_probability = None
        edge_percent = None
        under_edge_percent = None
        if projected is not None:
            mean, stddev = projected
            model_probability = over_probability(mean, stddev, prop.line)
            under_model_probability = 1.0 - model_probability
            if prop.over_price_american is not None:
                edge_percent = round(expected_value_percent(model_probability, prop.over_price_american), 2)
            if prop.under_price_american is not None:
                under_edge_percent = round(
                    expected_value_percent(under_model_probability, prop.under_price_american), 2
                )

        out.append(
            {
                "id": str(prop.id),
                "sport": player.sport,
                "source": prop.source,
                "player_name": player.full_name,
                "normalized_name": normalize_player_name(player.full_name),
                "player_id": str(player.id),
                # Underdog's payload carries no team array (constraint #17),
                # so game_id is never resolved at ingest time - always null
                # today, not a bug in this endpoint.
                "game_id": str(prop.game_id) if prop.game_id else None,
                "team_name": teams[player.current_team_id].name if player.current_team_id in teams else None,
                "opponent_name": None,
                "stat_type": prop.stat_type,
                "line": prop.line,
                "over_price_american": prop.over_price_american,
                "under_price_american": prop.under_price_american,
                # Null until the player has MIN_GAMES_FOR_PROJECTION
                # realized games for this stat_type (src/services/
                # projections.py) - never fabricated in the meantime.
                "projection": round(projection_value, 2) if projection_value is not None else None,
                "edge_percent": edge_percent,
                # Added for the custom parlay builder (POST /parlays/build),
                # which needs a real per-side probability to price an
                # "Under" leg, not just the over side /props/best already
                # ranked by. Additive fields only - over_price_american/
                # edge_percent/projection keep their original meaning.
                "model_probability": round(model_probability, 4) if model_probability is not None else None,
                "under_model_probability": round(under_model_probability, 4) if under_model_probability is not None else None,
                "under_edge_percent": under_edge_percent,
                "captured_at": prop.observed_at.isoformat(),
            }
        )
    return out


@router.get("/props")
async def props(sport: str | None = Query(default=None), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await prop_rows(db, sport)


@router.get("/props/best")
async def props_best(sport: str | None = Query(default=None), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Ranked by edge_percent - only props with a qualified projection
    (src/services/projections.py) carry one; the rest are excluded rather
    than sorted in as an implicit zero edge."""
    qualified = sorted(
        (row for row in await prop_rows(db, sport) if row["edge_percent"] is not None),
        key=lambda row: row["edge_percent"],
        reverse=True,
    )[:20]
    if not qualified:
        return {
            "items": [],
            "note": "no props have a qualified projection yet - each needs "
            f"{MIN_GAMES_FOR_PROJECTION} realized games for that player/stat_type",
        }
    return {"items": qualified}


async def signal_rows(db: AsyncSession, sport: str | None) -> list[dict[str, Any]]:
    """Only games that haven't been decided yet are real, bettable signals.

    FOUND LIVE 2026-09-04: nflverse's historical closing-line ingestion
    (src/ingest/nflverse.py, meant for backtesting - see that module's own
    "closing-line value" docstring) writes a TeamMarketLine row for every
    game in a season, finished or not. Without this filter, a finalized
    January game got priced with TODAY's team rating - a rating that
    already includes that exact game's own outcome - producing a 235% "EV"
    on a highly-favored team's underdog opponent. That isn't miscalibration,
    it's lookahead bias: the model was shown the answer before "predicting"
    it. Excluding final games fixes /signals, /parlays, /parlays/build, and
    the recommendations narrative all at once, since they all call this.
    """
    stmt = (
        select(TeamMarketLine, Game)
        .join(Game, TeamMarketLine.game_id == Game.id)
        .where(TeamMarketLine.market.in_(_MODELED_MARKETS), Game.status != "final")
    )
    if sport is not None:
        stmt = stmt.where(Game.sport == sport)
    stmt = stmt.distinct(
        TeamMarketLine.game_id, TeamMarketLine.market, TeamMarketLine.side, TeamMarketLine.source
    ).order_by(
        TeamMarketLine.game_id,
        TeamMarketLine.market,
        TeamMarketLine.side,
        TeamMarketLine.source,
        TeamMarketLine.observed_at.desc(),
    )
    rows = (await db.execute(stmt)).all()

    team_ids = {g.home_team_id for _, g in rows if g.home_team_id} | {
        g.away_team_id for _, g in rows if g.away_team_id
    }
    teams = await _team_lookup(db, team_ids)
    ratings = await _rating_lookup(db, team_ids)

    # Vig removal needs both sides of the same (game, market, source) quote
    # together (remove_vig_two_way), so group before emitting rows rather
    # than processing each side independently.
    paired: dict[tuple, dict[str, tuple[TeamMarketLine, Game]]] = {}
    for line, game in rows:
        key = (line.game_id, line.market, line.source)
        paired.setdefault(key, {})[line.side] = (line, game)

    out: list[dict[str, Any]] = []
    for (_, market, source), sides in paired.items():
        if market == "total":
            over_entry, under_entry = sides.get("over"), sides.get("under")
            if over_entry is None or under_entry is None:
                continue
            over_line, game = over_entry
            under_line, _ = under_entry

            home_rating = ratings.get(game.home_team_id)
            away_rating = ratings.get(game.away_team_id)
            if home_rating is None or away_rating is None:
                continue
            if not is_qualified(home_rating) or not is_qualified(away_rating):
                # Fewer than MIN_GAMES_FOR_TOTALS games played - the scoring
                # average isn't trustworthy yet, same "omit rather than
                # assume" discipline as the moneyline/spread branch below.
                continue
            home_name = teams[game.home_team_id].name if game.home_team_id in teams else "Home"
            away_name = teams[game.away_team_id].name if game.away_team_id in teams else "Away"
            matchup = f"{away_name} @ {home_name}"

            expected_total = expected_total_points(home_rating, away_rating)
            over_model_prob = total_over_probability(
                expected_total, over_line.line or 0.0, game.sport
            )
            over_selection = f"Over {over_line.line:.1f}" if over_line.line is not None else "Over"
            under_selection = f"Under {under_line.line:.1f}" if under_line.line is not None else "Under"

            fair_over, fair_under = None, None
            if over_line.price_american is not None and under_line.price_american is not None:
                fair_over, fair_under = remove_vig_two_way(
                    over_line.price_american, under_line.price_american
                )

            _emit_pair_rows(
                out,
                (
                    (over_line, over_model_prob, over_selection, fair_over),
                    (under_line, 1.0 - over_model_prob, under_selection, fair_under),
                ),
                market=market, source=source, matchup=matchup, game=game,
            )
            continue

        home_entry = sides.get("home")
        away_entry = sides.get("away")
        if home_entry is None or away_entry is None:
            # Only one side observed so far (e.g. the other side's poll
            # hasn't landed yet) - nothing to pair against, skip until both
            # exist rather than emit a one-sided fair probability.
            continue
        home_line, game = home_entry
        away_line, _ = away_entry

        home_rating_row = ratings.get(game.home_team_id)
        away_rating_row = ratings.get(game.away_team_id)
        if home_rating_row is None or away_rating_row is None:
            # No Elo history for one side yet (brand-new team, or the
            # sport's bootstrap hasn't run) - omit rather than assume the
            # 1500 default means something.
            continue
        home_rating, away_rating = home_rating_row.rating, away_rating_row.rating
        home_name = teams[game.home_team_id].name if game.home_team_id in teams else "Home"
        away_name = teams[game.away_team_id].name if game.away_team_id in teams else "Away"
        matchup = f"{away_name} @ {home_name}"

        if market == "moneyline":
            home_model_prob = moneyline_probability(home_rating, away_rating)
            home_selection, away_selection = f"{home_name} ML", f"{away_name} ML"
        else:  # spread
            home_model_prob = spread_cover_probability(
                home_rating, away_rating, home_line.line or 0.0, game.sport
            )
            home_selection = f"{home_name} {home_line.line:+.1f}" if home_line.line is not None else home_name
            away_selection = f"{away_name} {away_line.line:+.1f}" if away_line.line is not None else away_name

        fair_home, fair_away = None, None
        if home_line.price_american is not None and away_line.price_american is not None:
            fair_home, fair_away = remove_vig_two_way(home_line.price_american, away_line.price_american)

        _emit_pair_rows(
            out,
            (
                (home_line, home_model_prob, home_selection, fair_home),
                (away_line, 1.0 - home_model_prob, away_selection, fair_away),
            ),
            market=market, source=source, matchup=matchup, game=game,
        )
    return out


@router.get("/signals")
async def signals(sport: str | None = Query(default=None), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await signal_rows(db, sport)


@router.get("/odds/{game_id}/history")
async def odds_history(
    game_id: uuid.UUID,
    market: str | None = Query(default=None),
    source: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Full line-movement history for one game - deliberately every
    observation, NOT constraint #7's DISTINCT-ON-latest-only discipline,
    which applies to /props and /signals because those are current-state
    listings. This endpoint's entire purpose is the opposite: showing what
    the market did over time, which is exactly what team_market_lines'
    append-only design (src/models/facts.py) exists to make possible."""
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")

    stmt = select(TeamMarketLine).where(TeamMarketLine.game_id == game_id)
    if market is not None:
        stmt = stmt.where(TeamMarketLine.market == market)
    if source is not None:
        stmt = stmt.where(TeamMarketLine.source == source)
    stmt = stmt.order_by(TeamMarketLine.observed_at)
    rows = (await db.execute(stmt)).scalars().all()

    return {
        "game_id": str(game_id),
        "sport": game.sport,
        "lines": [
            {
                "id": str(row.id),
                "market": row.market,
                "side": row.side,
                "line": row.line,
                "price_american": row.price_american,
                "source": row.source,
                "line_type": row.line_type,
                "observed_at": row.observed_at.isoformat(),
            }
            for row in rows
        ],
    }


@router.get("/rankings/{sport}")
async def rankings(sport: str, db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    if sport not in get_settings().supported_sports:
        raise HTTPException(status_code=404, detail=f"unsupported sport {sport!r}")
    rows = (
        await db.execute(
            select(TeamRating, Team)
            .join(Team, TeamRating.team_id == Team.id)
            .where(TeamRating.sport == sport)
            .order_by(TeamRating.rating.desc())
        )
    ).all()
    return [
        {
            "team_id": str(team.id),
            "team_name": team.name,
            "sport": sport,
            "rating": round(rating.rating, 1),
            "updated_at": rating.updated_at.isoformat(),
        }
        for rating, team in rows
    ]


@router.get("/parlays")
async def parlays(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """A single suggested parlay from the current top-EV legs.

    Legs are combined assuming INDEPENDENCE - explicitly a simplification.
    The rebuild design's correlated joint-distribution model (so a moneyline
    and its matching spread aren't priced as if unrelated) is real future
    work, deferred alongside the rest of the contest system; faking
    correlation awareness here would be worse than being explicit about not
    having it yet.
    """
    all_signals = await signal_rows(db, sport=None)
    legs = sorted(
        (s for s in all_signals if s["price_american"] is not None),
        key=lambda s: s["ev_percent"],
        reverse=True,
    )[:3]
    if not legs:
        return {"legs": [], "combined_probability": None, "note": "no priced signals available yet"}

    combined_probability = 1.0
    for leg in legs:
        combined_probability *= leg["model_probability"]

    return {
        "legs": legs,
        "combined_probability": round(combined_probability, 4),
        "independent_legs_assumption": True,
        "note": "legs assumed independent - no correlated joint-distribution model yet",
    }


class ParlayLegRequest(BaseModel):
    kind: Literal["signal", "prop"]
    id: uuid.UUID
    # Only meaningful for a prop leg (a signal row is already one specific
    # side); defaults to "over" if omitted rather than rejecting the request.
    side: Literal["over", "under"] | None = None


class ParlayBuildRequest(BaseModel):
    legs: list[ParlayLegRequest]


@router.post("/parlays/build")
async def build_parlay(request: ParlayBuildRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Combine specific user-picked legs (signals and/or props, either
    side of a prop) into one parlay - unlike /parlays' own top-3-by-EV
    auto-pick, this prices exactly what the caller selected. Still assumes
    independence between legs, the same disclosed simplification /parlays
    already carries.

    A leg that doesn't resolve (unknown id, or the market has no price/no
    qualified projection yet) is reported in skipped_legs, never silently
    dropped or priced with a guessed number.
    """
    signals_by_id = {row["id"]: row for row in await signal_rows(db, sport=None)}
    props_by_id = {row["id"]: row for row in await prop_rows(db, sport=None)}

    resolved: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for leg in request.legs:
        leg_id = str(leg.id)
        if leg.kind == "signal":
            row = signals_by_id.get(leg_id)
            if row is None or row["price_american"] is None:
                skipped.append({"kind": "signal", "id": leg_id, "reason": "not found or unpriced"})
                continue
            resolved.append(
                {
                    "kind": "signal",
                    "id": leg_id,
                    "sport": row["sport"],
                    "context": row["matchup"],
                    "selection": row["selection"],
                    "price_american": row["price_american"],
                    "model_probability": row["model_probability"],
                    "fair_probability": row["fair_probability"],
                }
            )
            continue

        row = props_by_id.get(leg_id)
        if row is None:
            skipped.append({"kind": "prop", "id": leg_id, "reason": "not found"})
            continue
        side = leg.side or "over"
        if side == "over":
            price, probability = row["over_price_american"], row["model_probability"]
        else:
            price, probability = row["under_price_american"], row["under_model_probability"]
        if price is None or probability is None:
            skipped.append({"kind": "prop", "id": leg_id, "side": side, "reason": "not qualified or unpriced"})
            continue
        resolved.append(
            {
                "kind": "prop",
                "id": leg_id,
                "sport": row["sport"],
                "context": row["player_name"],
                "selection": f"{row['player_name']} {side.capitalize()} {row['line']} {row['stat_type']}",
                "price_american": price,
                "model_probability": probability,
                "fair_probability": None,
            }
        )

    if not resolved:
        return {
            "legs": [],
            "combined_probability": None,
            "combined_price_american": None,
            "skipped_legs": skipped,
            "independent_legs_assumption": True,
            "note": "no requested legs resolved to a priced signal or prop",
        }

    combined_probability = 1.0
    combined_decimal = 1.0
    for resolved_leg in resolved:
        combined_probability *= resolved_leg["model_probability"]
        combined_decimal *= american_to_decimal(resolved_leg["price_american"])

    return {
        "legs": resolved,
        "combined_probability": round(combined_probability, 4),
        "combined_price_american": decimal_to_american(combined_decimal),
        "skipped_legs": skipped,
        "independent_legs_assumption": True,
        "note": "legs assumed independent - no correlated joint-distribution model yet",
    }


@router.get("/recommendations")
async def recommendations(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The latest cached LLM narrative (src/services/recommendations.py),
    generated on a Celery schedule - never computed live in this request. A
    real generation call through this stack's local Ollama model takes
    ~78s, so this is always a fast read of the most recent
    RecommendationSnapshot row, not an LLM call."""
    snapshot = await db.scalar(
        select(RecommendationSnapshot).order_by(desc(RecommendationSnapshot.generated_at)).limit(1)
    )
    if snapshot is None:
        return {"narrative": None, "generated_at": None, "note": "no recommendation generated yet"}
    return {"narrative": snapshot.narrative, "generated_at": snapshot.generated_at.isoformat()}


@router.get("/calibration")
async def calibration(sport: str | None = None, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Latest walk-forward backtest result (src/services/backtest.py,
    scripts/run_calibration.py) per sport/market pair - a manually-run,
    occasional offline check, never computed live in this request. Returns
    the newest CalibrationReport row for each distinct (sport, market),
    not full history - a reader wants "is the model good right now," which
    is the latest report, not every past run."""
    stmt = select(CalibrationReport).order_by(desc(CalibrationReport.evaluated_at))
    if sport is not None:
        stmt = stmt.where(CalibrationReport.sport == sport)
    reports = (await db.execute(stmt)).scalars().all()

    latest_by_key: dict[tuple[str, str], CalibrationReport] = {}
    for report in reports:
        key = (report.sport, report.market)
        latest_by_key.setdefault(key, report)

    if not latest_by_key:
        return {"reports": [], "note": "no calibration report generated yet"}

    return {
        "reports": [
            {
                "sport": r.sport,
                "market": r.market,
                "seasons_used": r.seasons_used,
                "sample_size": r.sample_size,
                "brier_score": r.brier_score,
                "log_loss": r.log_loss,
                "passed_gate": r.passed_gate,
                "evaluated_at": r.evaluated_at.isoformat(),
            }
            for r in latest_by_key.values()
        ]
    }
