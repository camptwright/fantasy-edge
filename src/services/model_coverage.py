"""All-sport coverage, with quote usability separate from model eligibility."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from sqlalchemy import select, func, case
from src.models.facts import Game, PlayerGameStat
from src.services.stat_identity import canonical_stat


async def coverage(db, quotes):
    stat = case((PlayerGameStat.stat_type == 'ints_thrown', 'passing_interceptions'), else_=PlayerGameStat.stat_type)
    facts = (await db.execute(select(Game.sport, stat,
        func.count(func.distinct(func.row(PlayerGameStat.player_id, PlayerGameStat.game_id))),
        func.count(func.distinct(PlayerGameStat.game_id)), func.max(Game.game_time))
        .join(Game, Game.id == PlayerGameStat.game_id).where(Game.status == 'final')
        .group_by(Game.sport, stat))).all()
    history = {(sport, name): {'player_games': n, 'games': games,
        'latest_result_at': latest.isoformat() if latest else None} for sport, name, n, games, latest in facts}
    groups = defaultdict(list)
    for row in quotes:
        groups[(row['sport'], canonical_stat(row['stat_type']))].append(row)
    families = []
    for key in sorted(set(history) | set(groups)):
        rows = groups[key]
        blockers = Counter(r.get('exclusion_reason') for r in rows if not r.get('actionable'))
        families.append({'sport': key[0], 'stat_type': key[1], 'quotes': len(rows),
            'qualified_quotes': sum(r.get('model_probability') is not None for r in rows),
            'actionable_quotes': sum(bool(r.get('actionable')) for r in rows),
            'aliases_observed': sorted({r['stat_type'] for r in rows if r['stat_type'] != key[1]}),
            'blockers': dict(blockers), 'history': history.get(key, {}),
            'upcoming_history_gaps': [{'player': r['player_name'], 'source': r['source'], 'game_id': r['game_id']}
                for r in rows if r.get('exclusion_reason') == 'insufficient_history'][:20]})
    return {'as_of': datetime.now(timezone.utc).isoformat(), 'families': families,
        'note': 'Quote rows are not independent bets. Historical player/game counts deduplicate exact stat aliases. '
                'Actionability requires a confirmed recent offer, known future event, price, and projection.'}
