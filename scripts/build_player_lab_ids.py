"""Cache public Sleeper identity fields; never infer IDs from names."""
import json
import csv
import io
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import httpx


def run():
    response = httpx.get('https://api.sleeper.app/v1/players/nfl', timeout=45)
    response.raise_for_status()
    rows = response.json()
    identities = {str(pid): {key: str(row[key]).strip() for key in ('gsis_id', 'espn_id') if row.get(key)}
                  for pid, row in rows.items() if isinstance(row, dict)}
    crosswalk_url = 'https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv'
    crosswalk = httpx.get(crosswalk_url, timeout=45, follow_redirects=True)
    crosswalk.raise_for_status()
    candidates = defaultdict(lambda: defaultdict(set))
    for row in csv.DictReader(io.StringIO(crosswalk.text)):
        pid = row.get('sleeper_id')
        if not pid or pid == 'NA':
            continue
        for key in ('gsis_id', 'espn_id'):
            value = row.get(key)
            if value and value != 'NA': candidates[pid][key].add(value)
    conflicts = 0
    for pid, keys in candidates.items():
        target = identities.setdefault(pid, {})
        for key, values in keys.items():
            if target.get(key): values.add(target[key])
        if any(len(values) > 1 for values in keys.values()):
            identities[pid] = {}
            conflicts += 1
            continue
        for key, values in keys.items(): target[key] = next(iter(values))
    path = Path(__file__).resolve().parents[1]/'config/nfl_player_lab_ids.json'
    payload = {'fetched_at': datetime.now(timezone.utc).isoformat(),
               'source': ['https://api.sleeper.app/v1/players/nfl', crosswalk_url],
               'conflicts_excluded': conflicts, 'identities': identities}
    path.write_text(json.dumps(payload, sort_keys=True))
    print(json.dumps({'players': len(identities), 'path': str(path)}))


if __name__ == '__main__':
    run()
