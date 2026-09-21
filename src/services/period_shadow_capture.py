"""Read-only, bounded capture of otherwise blocked period quotes for research."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy import select, text, or_
from config.settings import get_settings
from src.models.facts import Game, PlayerPropLine, QuoteAvailability
from src.models.identity import Player
from src.services.period_shadow import predict
from src.services.settlement_binding import bind

MARKETS = [f'{period}_{stat}' for period in ('1q', '2q', '3q', '1h')
           for stat in ('passing_yards', 'receiving_yards', 'rec_yards', 'rushing_yards', 'receptions', 'rushing_attempts')]


def history_market(stat):
    period, suffix=stat.split('_',1)
    return period+'_'+{'rec_yards':'receiving_yards','rushing_attempts':'carries'}.get(suffix,suffix)


async def capture(db):
    await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
    now = datetime.now(timezone.utc)
    root = Path(get_settings().raw_archive_dir)
    candidates = sorted((root/'period-research-status').glob('*.json'), reverse=True)
    if not candidates:
        return {'status': 'missing_history', 'records': [], 'serving_enabled': False}
    status = json.loads(candidates[0].read_text())
    # Imported archives may retain original host paths. Resolve only the basename
    # under the known local archive directory, never an arbitrary artifact path.
    history_path = root/'period-history-validated'/Path(status['dataset_archive']).name
    published = status['generated_at']
    rows = (await db.execute(select(PlayerPropLine, Game, Player).join(Game, Game.id == PlayerPropLine.game_id)
        .join(Player, Player.id == PlayerPropLine.player_id)
        .join(QuoteAvailability, (QuoteAvailability.quote_id == PlayerPropLine.id) & (QuoteAvailability.kind == 'prop'))
        .where(Game.sport == 'nfl', Player.sport == 'nfl', Game.status == 'scheduled',
            or_(Game.game_type.is_(None), Game.game_type != 'PRE'),
            # Unknown start is intentionally not eligible for prospective capture.
            Game.game_time > now, PlayerPropLine.stat_type.in_(MARKETS),
            PlayerPropLine.observed_at <= now, QuoteAvailability.available.is_(True),
            QuoteAvailability.seen_at <= now, QuoteAvailability.seen_at >= now-timedelta(minutes=45))
        .order_by(PlayerPropLine.observed_at.desc(), PlayerPropLine.id).limit(501))).all()
    if not rows:
        return {'schema_version': 1, 'status': 'no_eligible_quotes', 'captured_at': now.isoformat(),
                'records': [], 'serving_enabled': False}
    if history_path.stat().st_size > 64_000_000:
        return {'status': 'history_exceeds_capture_budget', 'records': [], 'serving_enabled': False}
    payload = json.loads(history_path.read_text())
    wanted = {p.gsis_id for _, _, p in rows}
    history = [{**g, 'available_at': published, 'labels': [r for r in g['labels'] if r['player_id'] in wanted]}
               for g in payload['games']]
    records, seen = [], set()
    for quote, game, player in rows[:500]:
        key = (str(game.id), str(player.id), quote.stat_type, quote.source, quote.line)
        if key in seen:
            continue
        seen.add(key)
        market = history_market(quote.stat_type)
        result = predict(history, player.gsis_id, market, quote.line, now) if player.gsis_id else {'status': 'missing_gsis_identity'}
        # Source suffix identifies a book, NOT its product or jurisdiction.
        book = quote.source.split('_', 1)[1] if '_' in quote.source else None
        contract = bind({'book': book, 'product': None, 'jurisdiction': None,
            'sport': game.sport,
            'market': quote.stat_type, 'quote_id': str(quote.id), 'captured_at': now.isoformat()})
        records.append({'quote_id': str(quote.id), 'game_id': str(game.id), 'player_id': str(player.id),
            'market': quote.stat_type, 'line': quote.line, 'source': quote.source,
            'history_market':market,
            'over_price': quote.over_price_american, 'under_price': quote.under_price_american,
            'game_time': game.game_time.isoformat(), 'prediction': result, 'settlement_binding': contract})
    finished = datetime.now(timezone.utc)
    from src.services.event_weather import context as weather_context
    game_map={str(g.id):g for _,g,_ in rows}
    for record in records:
        record['context_experiment']={'recipe':'frozen_context_observation_v1',
            'weather':weather_context(game_map[record['game_id']],now),
            'numeric_adjustment':None,'serving_enabled':False}
    finished = datetime.now(timezone.utc)
    records = [r for r in records if datetime.fromisoformat(r['game_time']) > finished]
    return {'schema_version': 1, 'status': 'research', 'captured_at': finished.isoformat(),
        'code_hashes': {name: hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                        for name in ('period_shadow.py', 'settlement_binding.py', 'period_shadow_capture.py')},
        'history_sha256': hashlib.sha256(history_path.read_bytes()).hexdigest(),
        'history_published_at': published, 'records': records, 'truncated': len(rows)>500,
        'serving_enabled': False, 'note': 'Historical participation-conditioned candidate; no settlement or recommendation approval.'}
