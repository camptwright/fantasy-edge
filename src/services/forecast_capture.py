"""Immutable capture payload for the currently served baseline.

Run in a repeatable-read transaction. All records must still be pregame when
capture finishes; the output timestamp is not the old quote timestamp.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select, text
from src.api.routers.sportsbook import signal_rows, prop_rows
from src.models.facts import Game, TeamMarketLine
from src.models.ratings import TeamRating
from src.services.projections import project_stats
from src.services.serving_calibration import deployment_status
from src.services.serving_distributions import distribution_status
from src.services.player_features import snapshots
from src.services.news_evidence import headlines_for_players
from src.services.shadow_props import predict as shadow_predict, recipe_digest
from src.services.count_only_shadow import predict as count_only_predict
from config.settings import get_settings


def model_digest():
    from src.services.model_version import manifest
    return manifest()['model_version']


def shadow_predictions(feature, line, sigma, sport):
    existing = {name: {**prediction, 'recipe_version': recipe_digest()}
                for name, prediction in shadow_predict(feature, line, sigma).items()}
    return {**existing, **count_only_predict(feature, line, sport)}


def eligible(game, captured_at):
    return game is not None and game.status == 'scheduled' and game.game_time is not None and game.game_time > captured_at


async def capture(db):
    await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
    started = datetime.now(timezone.utc)
    signals = await signal_rows(db, None)
    props = await prop_rows(db, None, live_only=True)
    games = {str(g.id): g for g in (await db.scalars(select(Game).where(Game.status == 'scheduled'))).all()}
    ids = [uuid.UUID(s['id']) for s in signals]
    lines = {str(line.id): line for line in (await db.scalars(select(TeamMarketLine).where(
        TeamMarketLine.id.in_(ids)))).all()} if ids else {}
    ratings = {r.team_id: r for r in (await db.scalars(select(TeamRating))).all()}
    linked = [p for p in props if p.get('game_id') in games and p.get('actionable') and p.get('model_probability') is not None]
    projected = await project_stats(db, {(uuid.UUID(p['player_id']), p['stat_type']) for p in linked})
    features = await snapshots(db, linked, started)
    from src.services.market_shadow import forecasts as market_forecasts
    market_predictions = market_forecasts(linked, datetime.now(timezone.utc))
    news = headlines_for_players(Path(get_settings().raw_archive_dir) / 'news',
                                 {p['player_id']: p['player_name'] for p in linked}, started)
    records = []
    def rating_view(team_id):
        r = ratings.get(team_id)
        return None if r is None else {'rating': r.rating, 'games_played': r.games_played,
            'avg_points_scored': r.avg_points_scored, 'avg_points_allowed': r.avg_points_allowed}
    for signal in signals:
        line = lines.get(signal['id'])
        game = games.get(str(line.game_id)) if line else None
        if game is None:
            continue
        records.append({'kind': 'team', 'game_id': str(game.id), 'quote_id': signal['id'],
            'market': signal['market'], 'side': line.side, 'line': line.line,
            'prediction': signal, 'inputs': {'home': rating_view(game.home_team_id),
                                          'away': rating_view(game.away_team_id)}})
    for prop in linked:
        parameters = projected.get((uuid.UUID(prop['player_id']), prop['stat_type']))
        if parameters is None:
            continue
        records.append({'kind': 'player', 'game_id': prop['game_id'], 'quote_id': prop['id'],
            'player_id': prop['player_id'], 'market': prop['stat_type'], 'line': prop['line'],
            'injury_context': prop.get('injury_context'),
            'feature_snapshot': ({**features[prop['id']], 'news_headlines': news.get(prop['player_id'], []),
                'news_evidence_status': 'headline_evidence_only' if news.get(prop['player_id']) else 'none'}
                if prop['id'] in features else None),
            'shadow_predictions': {**shadow_predictions(features.get(prop['id']), prop['line'], parameters[1], prop['sport']),
                                   **market_predictions.get(prop['id'], {})},
            'prediction': prop, 'inputs': {'mean': parameters[0], 'stddev': parameters[1],
                'served_mean': prop['served_projection_mean'], 'served_stddev': prop['served_projection_stddev']}})
    finished = datetime.now(timezone.utc)
    accepted = [r for r in records if eligible(games.get(r['game_id']), finished)]
    from src.services.model_version import manifest
    versions = manifest()
    return {'schema_version': 1, 'capture_id': uuid.uuid4().hex,
        'started_at': started.isoformat(), 'captured_at': finished.isoformat(),
        'model_version': versions['model_version'], 'cohort_version': versions['cohort_version'],
        'version_manifest': versions,
        'model_status': 'experimental_user_overrides' if deployment_status()['enabled'] or distribution_status()['status'] == 'experimental_user_override' else 'baseline_uncalibrated',
        'calibration_deployment': {**deployment_status(), 'distributions': distribution_status()},
        'records': accepted, 'excluded': {'unlinked_or_unqualified_props': len(props)-len(linked),
                                       'not_pregame_at_completion': len(records)-len(accepted)},
        'notes': ['Scheduled capture of API calculations, not a log of every user page view.',
                  'Quote IDs reference append-only observations; captured_at is forecast availability.',
                  'Timestamped headline evidence is archived for research only; it does not affect numeric predictions or establish an injury/lineup fact.',
                  'Settlement rules and independent candidate shadow forecasts remain separate work.']}
