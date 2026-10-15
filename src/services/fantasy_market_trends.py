"""Observed market-index changes from matching archived league formats."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from src.services.fantasy_market import key, root
from src.services.dynasty_trade_planning import number


def trends(params, platform, ids, *, now=None, archive_root=None):
    now = now or datetime.now(timezone.utc)
    if params is None or platform not in ('sleeper', 'espn') or len(ids) > 12:
        return {'status': 'unsupported_selection', 'players': []}
    snapshots = []
    for path in sorted((Path(archive_root or root()) / key(params) / 'snapshots').glob('*.json'), reverse=True)[:32]:
        try:
            record = json.loads(path.read_text())
            observed = datetime.fromisoformat(record['captured_at'])
            if record['format'] == params and timedelta(0) <= now - observed <= timedelta(days=30):
                snapshots.append((observed, record))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    snapshots.sort(key=lambda row: row[0], reverse=True)
    if not snapshots or now - snapshots[0][0] > timedelta(days=2):
        return {'status': 'missing_current_market', 'players': []}
    current_at, current = snapshots[0]
    prior = next(((at, row) for at, row in reversed(snapshots[1:]) if current_at - at >= timedelta(days=1)), None)
    field = platform + '_id'

    def value(record, pid):
        found = [r for r in record.get('rows', []) if r.get(field) == str(pid)]
        return found[0]['value'] if len(found) == 1 and number(found[0].get('value')) else None

    players = []
    for pid in ids:
        latest = value(current, pid)
        previous = value(prior[1], pid) if prior else None
        players.append({'player_id': str(pid), 'current': latest, 'prior': previous,
                        'change': latest - previous if latest is not None and previous is not None else None})
    return {'status': 'observed_change' if prior else 'needs_second_observation',
            'captured_at': current_at.isoformat(), 'prior_captured_at': prior[0].isoformat() if prior else None,
            'players': players, 'note': 'Changes in matching FantasyCalc market-index observations; not a forecast of future price.'}
