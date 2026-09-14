"""Chronological player-prop baseline replay using actual pregame quotes.

One earliest quote per player/game/stat across books is graded. Prior-day results
only are used because exact result publication timestamps are unavailable.
Pushes are counted separately and are excluded from binary scoring.
"""
import statistics
from collections import defaultdict
from sqlalchemy import select, or_
from src.models.facts import Game, PlayerGameStat, PlayerPropLine
from src.services.backtest import BacktestPrediction
from src.services.projections import MIN_GAMES_FOR_PROJECTION, over_probability
from src.utils.normalize import normalize_stat_type


async def run_prop_backtest(db, sport):
    player_ids = list((await db.scalars(select(PlayerPropLine.player_id).join(
        Game, Game.id == PlayerPropLine.game_id).where(Game.sport == sport,
        Game.status == 'final', or_(Game.game_type.is_(None), Game.game_type != 'PRE'))
        .distinct().order_by(PlayerPropLine.player_id))).all())
    if not player_ids:
        return {}, {'no_linked_settled_quotes': 1}
    combined, exclusions = defaultdict(list), defaultdict(int)
    chronology = {}
    for offset in range(0, len(player_ids), 24):
        rows, counts = await _run_prop_batch(db, sport, player_ids[offset:offset+24], chronology)
        for stat, predictions in rows.items():
            combined[stat].extend(predictions)
        for reason, count in counts.items():
            exclusions[reason] += count
    # Candidate train/test splitting is chronological, not player-batch order.
    for predictions in combined.values():
        predictions.sort(key=lambda prediction: chronology[id(prediction)])
    return dict(combined), dict(exclusions)


async def _run_prop_batch(db, sport, player_ids, chronology=None):
    quotes = (await db.execute(select(PlayerPropLine, Game).join(
        Game, Game.id == PlayerPropLine.game_id
    ).where(Game.sport == sport, Game.status == 'final', PlayerPropLine.player_id.in_(player_ids),
            or_(Game.game_type.is_(None), Game.game_type != 'PRE')).order_by(
        Game.game_time.asc().nulls_last(), PlayerPropLine.observed_at.asc(), PlayerPropLine.id.asc()
    ))).all()
    if not quotes:
        return {}, {'no_linked_settled_quotes': 1}
    player_ids = {quote.player_id for quote, _ in quotes}
    history = (await db.execute(select(PlayerGameStat.player_id, PlayerGameStat.game_id,
        PlayerGameStat.stat_type, PlayerGameStat.value, Game.game_time).join(
        Game, Game.id == PlayerGameStat.game_id
    ).where(Game.sport == sport, Game.status == 'final',
            or_(Game.game_type.is_(None), Game.game_type != 'PRE'),
            PlayerGameStat.player_id.in_(player_ids)))).all()
    by_player = defaultdict(list)
    outcomes = {}
    for stat in history:
        if stat.game_time is None:
            continue
        key = (stat.player_id, normalize_stat_type(stat.stat_type))
        by_player[key].append((stat.game_time, stat.value))
        outcomes[(stat.player_id, stat.game_id, key[1])] = stat.value
    seen, predictions = set(), defaultdict(list)
    exclusions = defaultdict(int)
    for quote, game in quotes:
        if game.game_time is None or quote.observed_at >= game.game_time:
            exclusions['not_pregame'] += 1
            continue
        stat = normalize_stat_type(quote.stat_type)
        key = (quote.player_id, game.id, stat)
        # One sample per player/game/stat across books, avoiding duplicate weight.
        if key in seen:
            continue
        seen.add(key)
        outcome = outcomes.get(key)
        if outcome is None:
            exclusions['missing_result'] += 1
            continue
        if outcome == quote.line:
            exclusions['push'] += 1
            continue
        past = [value for when, value in by_player[(quote.player_id, stat)]
                if when.date() < quote.observed_at.date()]
        if len(past) < MIN_GAMES_FOR_PROJECTION:
            exclusions['insufficient_history'] += 1
            continue
        sigma = statistics.pstdev(past)
        if sigma <= 0:
            exclusions['zero_variance'] += 1
            continue
        prediction = BacktestPrediction(game.id, stat,
            over_probability(statistics.fmean(past), sigma, quote.line), float(outcome > quote.line))
        predictions[stat].append(prediction)
        if chronology is not None:
            chronology[id(prediction)] = (game.game_time, quote.observed_at, quote.id)
    return dict(predictions), dict(exclusions)
