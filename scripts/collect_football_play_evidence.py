"""Manually invoked, bounded public ESPN research collector. No fact writes."""
import json
from pathlib import Path
import httpx
from config.settings import get_settings
from src.scheduler.calibration import archive
from src.services.football_structured_pbp import athlete_id
from src.services.football_play_evidence import scoped_url


def run():
    root = Path(get_settings().raw_archive_dir)
    requests, reports, seen = 0, [], set()
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        for path in sorted((root/'football-core-pbp').glob('*.json'), reverse=True)[:20]:
            data = json.loads(path.read_text())
            league, event = data['league'], str(data['event_id'])
            if (league, event) in seen:
                continue
            seen.add((league, event))
            evidence, failures = {}, []
            for play in data['payload']['items']:
                if not (play.get('isPenalty') or play['type']['text'] in ('Penalty', 'Fumble', 'Fumble Recovery (Own)')):
                    continue
                for person in play.get('participants', []):
                    if person.get('type') not in ('passer', 'receiver', 'rusher'):
                        continue
                    player, pid = athlete_id(person, league), str(play['id'])
                    key = f'{pid}:{player}'
                    if key in evidence or 'playStatistics' not in person or requests >= 30:
                        continue
                    expected = f'/v2/sports/football/leagues/{league}/events/{event}/competitions/{event}/plays/{pid}/participants/{player}/statistics/0'
                    try:
                        url = scoped_url(person['playStatistics']['$ref'], expected)
                        requests += 1
                        response = client.get(url)
                        response.raise_for_status()
                        evidence[key] = response.json()
                    except (ValueError, httpx.HTTPError):
                        failures.append(key)
            output = archive('football-play-stat-evidence', {'league': league, 'event_id': event,
                'core_archive': str(path), 'evidence': evidence, 'failures': failures})
            reports.append({'event_id': event, 'records': len(evidence), 'failures': len(failures), 'archive': str(output)})
    print(json.dumps({'requests': requests, 'request_cap': 30, 'reports': reports}))


if __name__ == '__main__':
    run()
