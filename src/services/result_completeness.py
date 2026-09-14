"""Bounded, quote-scoped completeness; unknown participation is not a zero/DNP."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from src.models.facts import Game, PlayerPropLine, PlayerGameStat
from src.models.governance import ResultCorrection
from src.services.stat_identity import canonical_stat, canonical_results
from src.services.prop_requirements import requirement


async def status(db, sport=None, offset=0):
    now = datetime.now(timezone.utc)
    query = (select(Game.sport, PlayerPropLine.player_id,
        PlayerPropLine.game_id, PlayerPropLine.stat_type).join(Game, Game.id == PlayerPropLine.game_id)
        .where(Game.status == 'final', Game.game_time >= now-timedelta(days=14), Game.game_time <= now)
        .distinct().order_by(Game.sport, PlayerPropLine.game_id, PlayerPropLine.player_id,
                            PlayerPropLine.stat_type))
    if sport is not None:
        query = query.where(Game.sport == sport)
    expected = (await db.execute(query.offset(offset).limit(5001))).all()
    truncated = len(expected) > 5000
    expected = expected[:5000]
    games = {r.game_id for r in expected}
    rows = (await db.execute(select(PlayerGameStat.player_id, PlayerGameStat.game_id,
        PlayerGameStat.stat_type, PlayerGameStat.value).where(PlayerGameStat.game_id.in_(games)))).all() if games else []
    values = canonical_results(rows)
    participated = {(r.player_id, r.game_id) for r in rows}
    pending = set((await db.execute(select(PlayerGameStat.player_id, PlayerGameStat.game_id)
        .join(ResultCorrection, ResultCorrection.stat_id == PlayerGameStat.id).where(
            PlayerGameStat.game_id.in_(games), ResultCorrection.status == 'pending'))).all()) if games else set()
    counts = Counter()
    missing = []
    seen = set()
    for row_sport, player, game, raw_stat in expected:
        stat = canonical_stat(raw_stat)
        key = (player, game, stat)
        if key in seen:
            continue
        seen.add(key)
        state = ('pending_correction' if (player, game) in pending else
                 'present' if key in values else
                 'missing_stat' if (player, game) in participated else 'participation_unconfirmed')
        counts[(row_sport, stat, state)] += 1
        if state != 'present' and len(missing) < 100:
            missing.append({'sport': row_sport, 'player_id': str(player), 'game_id': str(game),
                            'stat': stat, 'status': state, 'model_requirement': requirement(stat)})
    return {'checked_at': now.isoformat(), 'window_days': 14,
        'sport': sport, 'offset': offset, 'next_offset': offset+5000 if truncated else None,
        'scope': 'unique player/game/stat combinations with stored props; not full roster coverage',
        'truncated': truncated, 'expected_outcomes': len(seen),
        'counts': [{'sport': s, 'stat': st, 'status': state, 'outcomes': n,
                    'model_requirement': requirement(st)}
                   for (s, st, state), n in sorted(counts.items())], 'review_sample': missing,
        'note': 'Unknown-time finals are outside this dated report. Missing outcomes never imply zero or a sportsbook void.'}
