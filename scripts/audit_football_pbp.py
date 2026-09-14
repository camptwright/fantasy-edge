"""Bounded audit of saved official payloads; no provider calls or fact writes."""
import json
from collections import Counter
from pathlib import Path
from config.settings import get_settings
from src.services.football_pbp_validation import audit
from src.scheduler.calibration import archive


def run():
    rows, seen = [], set()
    for path in sorted((Path(get_settings().raw_archive_dir)/'result-observations').glob('*.json'), reverse=True)[:2000]:
        data = json.loads(path.read_text())
        if data.get('provider') not in ('espn_nfl', 'espn_ncaaf'):
            continue
        key = (data['provider'], data['event_id'])
        if key in seen:
            continue
        seen.add(key)
        rows.append({'sport': data['provider'].removeprefix('espn_'),
            'source_archive': str(path), **audit(data['payload'], data['event_id'])})
        if len(rows) >= 20:
            break
    output = {'sample_limit': 20, 'archives_scan_limit': 2000, 'games': len(rows),
        'timeline_passes': sum(r['timeline_checks_passed'] for r in rows),
        'blockers': dict(Counter(b for r in rows for b in r['timeline_blockers'])),
        'player_props_enabled': False, 'reports': rows}
    path = archive('football-pbp-audit', output)
    print(json.dumps({'archive': str(path), **{k: v for k, v in output.items() if k != 'reports'}}))


if __name__ == '__main__':
    run()
