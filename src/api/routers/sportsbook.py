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
from datetime import datetime, timezone, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.db.client import get_db
from src.models.facts import Game, PlayerPropLine, TeamMarketLine, PlayerGameStat, QuoteAvailability
from src.models.governance import CalibrationReport
from src.models.identity import Player, Team
from src.models.ratings import TeamRating
from src.services.elo import moneyline_probability, spread_cover_probability, implied_margin
from src.services.serving_calibration import calibrate_home_probability, deployment_status
from src.services.serving_distributions import prop_parameters, spread_probability, distribution_status
from src.services.projections import MIN_GAMES_FOR_PROJECTION, over_probability, project_stats
from src.services.quote_eligibility import availability, exclusion
from src.services.stat_identity import canonical_stat
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
                "game_id": str(game.id),
                "actionable": True,
                "sport": game.sport,
                "market": market,
                "selection": selection,
                "bookmaker": source,
                "price_american": line.price_american,
                "model_probability": round(model_prob, 4),
                "baseline_model_probability": round(model_prob, 4),
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


async def prop_rows(db: AsyncSession, sport: str | None, *, live_only: bool = False,
                    quote_ids: set[uuid.UUID] | None = None,
                    history_page: tuple[int, int] | None = None) -> list[dict[str, Any]]:
    stmt = select(PlayerPropLine, Player).join(Player, PlayerPropLine.player_id == Player.id)
    if sport is not None:
        stmt = stmt.where(Player.sport == sport)
    stmt = stmt.distinct(
        PlayerPropLine.player_id, PlayerPropLine.stat_type, PlayerPropLine.source, PlayerPropLine.game_id
    ).order_by(
        PlayerPropLine.player_id,
        PlayerPropLine.stat_type,
        PlayerPropLine.source,
        PlayerPropLine.game_id,
        PlayerPropLine.observed_at.desc(),
        PlayerPropLine.id.desc(),
    )
    if live_only or quote_ids is not None or history_page is not None:
        # Select latest BEFORE filtering IDs/freshness: an old offer must
        # never reappear when its replacement is withdrawn or unpriced.
        latest = stmt.with_only_columns(PlayerPropLine.id).subquery()
        stmt = select(PlayerPropLine, Player).join(Player, Player.id == PlayerPropLine.player_id).where(
            PlayerPropLine.id.in_(select(latest.c.id)))
        if quote_ids is not None:
            stmt = stmt.where(PlayerPropLine.id.in_(quote_ids))
        if live_only:
            now = datetime.now(timezone.utc)
            stmt = stmt.join(Game, Game.id == PlayerPropLine.game_id).join(QuoteAvailability,
                (QuoteAvailability.quote_id == PlayerPropLine.id) & (QuoteAvailability.kind == 'prop')).where(
                Game.status == 'scheduled', Game.game_time.is_not(None), Game.game_time > now,
                QuoteAvailability.available.is_(True), QuoteAvailability.seen_at <= now,
                QuoteAvailability.seen_at >= now-timedelta(seconds=2700),
                PlayerPropLine.observed_at <= now,
                (PlayerPropLine.over_price_american.is_not(None) | PlayerPropLine.under_price_american.is_not(None)))
        if history_page is not None:
            offset, limit = history_page
            stmt = stmt.order_by(PlayerPropLine.id).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).all()
    if not rows:
        return []

    team_ids = {row.Player.current_team_id for row in rows if row.Player.current_team_id}
    teams = await _team_lookup(db, team_ids)
    projections = await project_stats(db, {(player.id, prop.stat_type) for prop, player in rows})
    game_ids = {prop.game_id for prop, player in rows if prop.game_id}
    games = {g.id: g for g in (await db.scalars(select(Game).where(Game.id.in_(game_ids)))).all()} if game_ids else {}
    seen = await availability(db, 'prop', [prop.id for prop, _ in rows])
    from pathlib import Path
    from src.services.injury_evidence import snapshots as injury_snapshots, unavailable, for_game, game_snapshots
    context_time = datetime.now(timezone.utc)
    injury_context = await injury_snapshots(db, [{'player_id': str(player.id)} for _, player in rows],
        Path(get_settings().raw_archive_dir) / 'espn_injuries', context_time)
    event_injuries = game_snapshots(Path(get_settings().raw_archive_dir) / 'football_availability', context_time)

    out = []
    for prop, player in rows:
        game = games.get(prop.game_id)
        reason = exclusion(game, prop, seen.get(prop.id))
        from src.services.prop_requirements import requirement
        reason = reason or requirement(prop.stat_type)
        context = injury_context.get(str(player.id))
        context = for_game(context, game, (context or {}).get('provider_athlete_ids', []), event_injuries, context_time)
        if reason is None and context.get('game_availability', {}).get('hold_recommendation'):
            reason = 'game_availability_review_required'
        if reason is None and game and game.game_time and 0 <= (game.game_time-context_time).total_seconds() <= 86400 and unavailable(context):
            reason = 'official_injured_list'
        market_probability = None
        if prop.over_price_american is not None and prop.under_price_american is not None:
            market_probability, _ = remove_vig_two_way(prop.over_price_american, prop.under_price_american)
        projected = projections.get((player.id, prop.stat_type))
        projection_value = projected[0] if projected is not None else None
        model_probability = None
        under_model_probability = None
        edge_percent = None
        under_edge_percent = None
        baseline_probability = None
        calibration_id = None
        served_mean = served_stddev = None
        if projected is not None:
            mean, stddev = projected
            baseline_probability = over_probability(mean, stddev, prop.line)
            mean, stddev, calibration_id = prop_parameters(mean, stddev, player.sport,
                canonical_stat(prop.stat_type), reason is None)
            served_mean, served_stddev = mean, stddev
            projection_value = mean
            model_probability = over_probability(mean, stddev, prop.line)
            under_model_probability = 1.0 - model_probability
            if reason is None and prop.over_price_american is not None:
                edge_percent = round(expected_value_percent(model_probability, prop.over_price_american), 2)
            if reason is None and prop.under_price_american is not None:
                under_edge_percent = round(
                    expected_value_percent(under_model_probability, prop.under_price_american), 2
                )

        out.append(
            {
                "id": str(prop.id),
                "actionable": reason is None and projected is not None and
                    (prop.over_price_american is not None or prop.under_price_american is not None),
                "exclusion_reason": reason or ('insufficient_history' if projected is None else
                    'unpriced' if prop.over_price_american is None and prop.under_price_american is None else None),
                "game_time": game.game_time.isoformat() if game and game.game_time else None,
                "game_status": game.status if game else None,
                "last_seen_at": seen[prop.id].seen_at.isoformat() if prop.id in seen else None,
                "sport": player.sport,
                "source": prop.source,
                "player_name": player.full_name,
                "normalized_name": normalize_player_name(player.full_name),
                "player_id": str(player.id),
                "injury_context": context,
                # Underdog's payload carries no team array (constraint #17),
                # so game_id is never resolved at ingest time - always null
                # today, not a bug in this endpoint.
                "game_id": str(prop.game_id) if prop.game_id else None,
                "team_name": teams[player.current_team_id].name if player.current_team_id in teams else None,
                "opponent_name": None,
                "stat_type": prop.stat_type,
                "canonical_stat_type": canonical_stat(prop.stat_type),
                "market_fair_probability": market_probability,
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
                "baseline_model_probability": round(baseline_probability, 4) if baseline_probability is not None else None,
                "baseline_projection": round(projected[0], 2) if projected is not None else None,
                "served_projection_mean": served_mean,
                "served_projection_stddev": served_stddev,
                "calibration_candidate_id": calibration_id,
                "calibration_status": 'experimental_user_override' if calibration_id else 'baseline',
                "captured_at": prop.observed_at.isoformat(),
            }
        )
    return out


@router.get("/props")
async def props(sport: str | None = Query(default=None), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return await prop_rows(db, sport)


def compact_prop(row):
    # Keep view-model fields, not repeated archives or redundant model inputs.
    keys = ('id', 'sport', 'source', 'player_name', 'player_id', 'game_id', 'team_name',
            'stat_type', 'line', 'over_price_american', 'under_price_american', 'projection',
            'edge_percent', 'under_edge_percent', 'model_probability', 'under_model_probability',
            'game_time', 'game_status', 'last_seen_at', 'actionable', 'exclusion_reason')
    result = {k: row.get(k) for k in keys}
    context = row.get('injury_context') or {}
    result['injury_context'] = {'status': context.get('status'),
        'game_availability': {'status': (context.get('game_availability') or {}).get('status')}}
    return result


@router.get('/props/live')
async def live_props(sport: str | None = None, limit: int = Query(200, ge=1, le=200),
                     offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db)):
    rows = [r for r in await prop_rows(db, sport, live_only=True) if r['actionable']]
    rows.sort(key=lambda r: (-max(r['edge_percent'] if r['edge_percent'] is not None else -1e9,
                                  r['under_edge_percent'] if r['under_edge_percent'] is not None else -1e9), r['id']))
    return [compact_prop(r) for r in rows[offset:offset+limit]]


@router.get('/props/history')
async def prop_history(sport: str | None = None, limit: int = Query(100, ge=1, le=200),
                       offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db)):
    return await prop_rows(db, sport, history_page=(offset,limit))


@router.get("/props/best")
async def props_best(sport: str | None = Query(default=None), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Ranked by edge_percent - only props with a qualified projection
    (src/services/projections.py) carry one; the rest are excluded rather
    than sorted in as an implicit zero edge."""
    qualified = sorted(
        (row for row in await prop_rows(db, sport, live_only=True) if row.get('actionable') and row["edge_percent"] is not None),
        key=lambda row: row["edge_percent"],
        reverse=True,
    )[:20]
    if not qualified:
        return {
            "items": [],
            "note": "No actionable qualified projection: each offer needs a verified future event, "
            f"fresh source confirmation, a price, and {MIN_GAMES_FOR_PROJECTION} variable historical results.",
        }
    return {"items": qualified}


async def signal_rows(db: AsyncSession, sport: str | None, *, quote_ids: set[uuid.UUID] | None = None) -> list[dict[str, Any]]:
    """Only games that haven't started yet are real, bettable signals.

    FOUND LIVE 2026-09-04: nflverse's historical closing-line ingestion
    (src/ingest/nflverse.py, meant for backtesting - see that module's own
    "closing-line value" docstring) writes a TeamMarketLine row for every
    game in a season, finished or not. Without a status filter, a finalized
    January game got priced with TODAY's team rating - a rating that
    already includes that exact game's own outcome - producing a 235% "EV"
    on a highly-favored team's underdog opponent. That isn't miscalibration,
    it's lookahead bias: the model was shown the answer before "predicting"
    it.

    FOUND LIVE 2026-09-05: excluding only "final" wasn't enough - an
    in-progress MLB game (Reds hosting the Brewers, well into the game) was
    still being priced against the STATIC pre-game Elo rating, producing a
    617% "EV" on a live moneyline that had already moved to +1139 because
    the market (unlike this model) knows the live score. Elo/totals is a
    pre-game-only baseline with no in-play win-probability adjustment, so
    the fix is the same shape as the first bug: only "scheduled" games
    (src/ingest/{espn,mlb,nhl}.py's only three status values are scheduled/
    in_progress/final) get a real, honest signal. Excluding both fixes
    /signals, /parlays, /parlays/build, and the recommendations narrative
    all at once, since they all call this.
    """
    stmt = (
        select(TeamMarketLine, Game)
        .join(Game, TeamMarketLine.game_id == Game.id)
        .where(TeamMarketLine.market.in_(_MODELED_MARKETS), Game.status == "scheduled")
    )
    if sport is not None:
        stmt = stmt.where(Game.sport == sport)
    if quote_ids is not None:
        # Retain opposing legs for vig removal, but only referenced games.
        stmt = stmt.where(Game.id.in_(select(TeamMarketLine.game_id).where(TeamMarketLine.id.in_(quote_ids))))
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

    seen = await availability(db, 'team', [line.id for line, _ in rows])
    # Preserve unknown-time fixtures in storage; they are explicitly not
    # actionable until a known future start and fresh source confirmation.
    rows = [(line, game) for line, game in rows if exclusion(game, line, seen.get(line.id)) is None]

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

        distribution_id = None
        if market == "moneyline":
            baseline_home_prob = moneyline_probability(home_rating, away_rating)
            home_model_prob = calibrate_home_probability(baseline_home_prob, game.sport, market)
            home_selection, away_selection = f"{home_name} ML", f"{away_name} ML"
        else:  # spread
            baseline_home_prob = spread_cover_probability(
                home_rating, away_rating, home_line.line or 0.0, game.sport
            )
            pregame = game.game_time is not None and game.game_time > datetime.now(timezone.utc)
            home_model_prob, distribution_id = spread_probability(implied_margin(home_rating, away_rating),
                home_line.line or 0.0, baseline_home_prob, game.sport, pregame)
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
        if market == 'moneyline' and game.sport == 'ncaaf':
            status = deployment_status()
            for row, baseline in zip(out[-2:], (baseline_home_prob, 1.0-baseline_home_prob)):
                row['baseline_model_probability'] = round(baseline, 4)
                row['calibration_status'] = status['status']
                row['calibration_candidate_id'] = status['candidate_id'] if status['enabled'] else None
        if market == 'spread' and game.sport == 'ncaaf':
            for row, baseline in zip(out[-2:], (baseline_home_prob, 1.0-baseline_home_prob)):
                row['baseline_model_probability'] = round(baseline, 4)
                row['calibration_status'] = 'experimental_user_override' if distribution_id else 'baseline'
                row['calibration_candidate_id'] = distribution_id
    for row in out:
        row['last_seen_at'] = seen[uuid.UUID(row['id'])].seen_at.isoformat()
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
    candidates = sorted(
        (s for s in all_signals if s["price_american"] is not None),
        key=lambda s: s["ev_percent"],
        reverse=True,
    )
    legs, games = [], set()
    for row in candidates:
        if row['game_id'] in games:
            continue
        legs.append(row)
        games.add(row['game_id'])
        if len(legs) == 3:
            break
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

    # No joint model exists yet: reject repeated events entirely, including
    # duplicate/opposite legs and same-game props across different sources.
    events = set()
    for leg in request.legs:
        row = (signals_by_id if leg.kind == 'signal' else props_by_id).get(str(leg.id))
        if row is None:
            continue  # Unknown IDs retain the documented skipped_legs contract.
        if not row.get('actionable'):
            raise HTTPException(422, 'Every parlay leg must be a fresh, priced pregame offer with a projection')
        event = row.get('game_id')
        if event is None or event in events:
            raise HTTPException(422, 'Duplicate, contradictory, and same-game legs require a joint model and are not supported')
        events.add(event)

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
    RecommendationSnapshot row, not an LLM call.

    The freshness/quote-evidence gate itself lives in
    recommendations.get_valid_narrative - shared with
    src/scheduler/tasks.py's post_narrative_to_dashboard so both call sites
    apply the exact same staleness rule."""
    from src.services.recommendations import get_valid_narrative

    return await get_valid_narrative(db)


@router.get("/calibration/live")
def live_calibration() -> dict[str, Any]:
    from pathlib import Path
    from src.services.forecast_grading import latest_report
    return latest_report(Path(get_settings().raw_archive_dir) / 'grading')


@router.get("/calibration/deployment")
def calibration_deployment() -> dict[str, Any]:
    return {**deployment_status(), 'distributions': distribution_status()}


@router.get('/calibration/prop-readiness')
async def ncaaf_prop_readiness(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    from src.services.prop_readiness import latest_research, readiness
    from starlette.concurrency import run_in_threadpool
    rows = (await db.execute(select(PlayerGameStat.stat_type, func.count(PlayerGameStat.id),
        func.count(func.distinct(PlayerGameStat.game_id))).join(Game, Game.id == PlayerGameStat.game_id)
        .where(Game.sport == 'ncaaf', Game.status == 'final').group_by(PlayerGameStat.stat_type))).all()
    facts = {stat: {'rows': count, 'games': games} for stat, count, games in rows}
    research = await run_in_threadpool(latest_research)
    return readiness(await prop_rows(db, 'ncaaf'), facts, research)


@router.get('/calibration/coverage')
async def all_sport_coverage(db: AsyncSession = Depends(get_db)):
    from src.services.model_coverage import coverage
    return await coverage(db, await prop_rows(db, None))


@router.get('/calibration/odds-status')
async def odds_status(db: AsyncSession = Depends(get_db)):
    from redis.asyncio import Redis
    from src.services.odds_pacing import status, apply_nfl_window
    settings = get_settings()
    async with Redis.from_url(settings.redis_url, decode_responses=True) as redis:
        report = await status(redis, settings)
    if settings.odds_api_nfl_props_priority:
        now = datetime.now(timezone.utc)
        # Paid pregame collection intentionally requires a known kickoff.
        kickoff = await db.scalar(select(Game.game_time).where(
            Game.sport == 'nfl', Game.status == 'scheduled',
            Game.game_time.is_not(None), Game.game_time > now
        ).order_by(Game.game_time).limit(1))
        apply_nfl_window(report, kickoff, now)
    return report


@router.get('/calibration/prop-provider-status')
async def prop_provider_status():
    import json
    from redis.asyncio import Redis
    from src.ingest.aggregate_props import BOOKS
    settings = get_settings()
    now = datetime.now(timezone.utc)
    providers = {}
    async with Redis.from_url(settings.redis_url, decode_responses=True) as redis:
        for provider in ('sgo', 'parlay'):
            raw = await redis.get(f'aggregate:{provider}:status')
            providers[provider] = {
                'configured': bool(settings.sportsgameodds_api_key if provider == 'sgo' else settings.parlay_api_key),
                'bookmakers': sorted(BOOKS[provider]),
                'daily_limit': settings.sportsgameodds_daily_objects if provider == 'sgo' else settings.parlay_daily_credits,
                'reserved_today': int(await redis.get(f'aggregate:{provider}:spent:{now:%Y-%m-%d}') or 0),
                'unit': 'event_objects' if provider == 'sgo' else 'credits',
                'blocked_seconds': max(0, await redis.ttl(f'aggregate:{provider}:blocked')),
                'last_response': json.loads(raw) if raw else None,
            }
    return {'enabled': settings.aggregate_props_enabled, 'providers': providers,
            'dfs_actionable': False, 'direct_underdog_scheduled': False,
            'note': 'Initial limited bookmaker/market coverage. Source timestamps control freshness. The Odds API budget is independent.'}


@router.get('/calibration/result-repair')
async def result_repair_status(db: AsyncSession = Depends(get_db)):
    from src.services.result_repair_status import status
    return await status(db)


@router.get('/calibration/result-completeness')
async def result_completeness(sport: str | None = None, offset: int = Query(0, ge=0),
                              db: AsyncSession = Depends(get_db)):
    from src.services.result_completeness import status
    return await status(db, sport=sport, offset=offset)


@router.get('/calibration/context-readiness')
def context_readiness() -> dict[str, Any]:
    from pathlib import Path
    from src.services.context_readiness import readiness
    settings = get_settings()
    return readiness(Path(settings.raw_archive_dir), bool(settings.fantasy_news_rss_urls.strip()))


@router.get('/calibration/evaluation-status')
def evaluation_status():
    from pathlib import Path
    from src.services.evaluation_status import status
    from src.services.model_version import manifest
    settings = get_settings()
    return {**status(Path(settings.raw_archive_dir), settings.supported_sports), 'serving_versions': manifest()}


@router.get('/calibration/active-slate')
def active_slate_validation():
    from pathlib import Path
    from src.services.evaluation_status import latest
    report, _ = latest(Path(get_settings().raw_archive_dir) / 'active-slate-validation')
    if not report:
        return {'status': 'not_yet_checked', 'stale': True}
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(report['checked_at'])).total_seconds()
        stale = not 0 <= age <= 3600
    except (KeyError, ValueError, TypeError):
        stale = True
    return {**report, 'stale': stale, 'schedule_seconds': 1800}


@router.get('/calibration/research')
def shadow_research_scorecards():
    report = live_calibration()
    return {'status': report.get('status'), 'graded_at': report.get('graded_at'),
        'shadow_reports': report.get('shadow_reports', []), 'automatic_deployment': False}


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
