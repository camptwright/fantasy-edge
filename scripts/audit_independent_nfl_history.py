"""Resumable public ESPN final-boxscore audit, at most 20 new requests per run."""
import json
from collections import defaultdict
from pathlib import Path
import httpx
from config.settings import get_settings
from src.ingest.nflverse import _nflreadpy
from src.scheduler.calibration import archive
from src.services.independent_football_results import compare, crosswalk


def run():
    root = Path(get_settings().raw_archive_dir)
    nfl = _nflreadpy()
    identity_rows = nfl.load_players().select(['gsis_id', 'espn_id']).to_dicts()
    identity_source = archive('independent-nfl-crosswalk', {'rows': identity_rows})
    identities = crosswalk(identity_rows)
    games = nfl.load_schedules([2024, 2025]).to_dicts()
    boxes = defaultdict(list)
    for row in nfl.load_player_stats([2024, 2025]).to_dicts():
        boxes[row['game_id']].append(row)
    previous = set()
    for path in (root/'independent-nfl-final-audit').glob('*.json'):
        saved = json.loads(path.read_text())
        if 'counts' in saved:
            previous.add(saved['game_id'])
    results = []
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        for game in sorted(games, key=lambda g: (g['gameday'], g['game_id'])):
            if game['game_id'] in previous or game.get('home_score') is None or game.get('game_type') == 'PRE':
                continue
            event = str(game.get('espn') or '')
            if not event.isdigit():
                continue
            try:
                response = client.get('https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary', params={'event': event})
                response.raise_for_status()
                payload = response.json()
                source = archive('independent-nfl-final-input', {'schedule': game,
                    'nflverse_box': boxes[game['game_id']], 'espn_summary': payload, 'crosswalk_archive': identity_source})
                result = compare(payload, game, boxes[game['game_id']], identities)
                result['input_archive'] = source
            except (httpx.HTTPError, ValueError) as exc:
                result = {'game_id': game['game_id'], 'error_type': type(exc).__name__}
            archive('independent-nfl-final-audit', result)
            results.append({k: v for k, v in result.items() if k not in ('comparisons', 'input_archive')})
            if len(results) >= 20:
                break
    print(json.dumps({'games_checked': len(results), 'previously_checked': len(previous), 'reports': results}))


if __name__ == '__main__':
    run()
