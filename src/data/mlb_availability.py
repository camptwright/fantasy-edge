"""Official MLB roster status, keyed by MLB person ID."""
from datetime import datetime, timezone
import httpx


async def fetch_roster_status():
    async with httpx.AsyncClient(base_url='https://statsapi.mlb.com/api/v1', timeout=30) as client:
        response = await client.get('/teams', params={'sportId': 1})
        response.raise_for_status()
        rows = []
        for team in response.json()['teams']:
            response = await client.get(f'/teams/{team["id"]}/roster', params={'rosterType': 'fullRoster'})
            response.raise_for_status()
            observed = datetime.now(timezone.utc).isoformat()
            for row in response.json()['roster']:
                person, status = row.get('person', {}), row.get('status', {})
                if not person.get('id') or not status.get('code'):
                    continue
                rows.append({'sport': 'mlb', 'athlete_id': str(person['id']),
                    'provider': 'mlb_stats_api', 'status': status['code'],
                    'description': status.get('description'), 'observed_at': observed,
                    'reported_at': observed, 'timestamp_basis': 'current_roster_observation',
                    'team_id': str(team['id'])})
        return rows
