"""Completed NBA boxscores from the existing ESPN schedule provider."""
import math
from config.settings import get_settings

SOURCE = 'espn_nba'
FIELDS = {'PTS': 'points', 'REB': 'rebounds', 'AST': 'assists', 'STL': 'steals',
          'BLK': 'blocks', 'TO': 'turnovers', 'OREB': 'offensive_rebounds', 'DREB': 'defensive_rebounds'}
COMBOS = {'points_rebounds_assists': ('points', 'rebounds', 'assists'),
          'points_rebounds': ('points', 'rebounds'), 'points_assists': ('points', 'assists'),
          'rebounds_assists': ('rebounds', 'assists'), 'steals_blocks': ('steals', 'blocks')}


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None


def participants(payload):
    merged = {}
    for team in payload.get('boxscore', {}).get('players', []):
        for block in team.get('statistics', []):
            labels = block.get('labels', [])
            for row in block.get('athletes', []):
                athlete = row.get('athlete', {})
                external_id = str(athlete.get('id') or '')
                values = row.get('stats', [])
                if row.get('didNotPlay') is not False or not external_id or not athlete.get('displayName'):
                    continue
                if len(labels) != len(values):
                    continue
                raw = dict(zip(labels, values))
                stats = {stat: number(raw.get(label)) for label, stat in FIELDS.items()}
                stats = {k: v for k, v in stats.items() if v is not None}
                # ESPN may round a short appearance to zero minutes. Explicit
                # didNotPlay=false and numeric stats establish participation.
                minutes = number(raw.get('MIN'))
                if minutes is not None:
                    stats['minutes'] = minutes
                made = str(raw.get('3PT', '')).split('-')
                if len(made) == 2 and number(made[0]) is not None and number(made[1]) is not None and float(made[0]) <= float(made[1]):
                    stats['three_pointers_made'] = float(made[0])
                if not stats:
                    continue
                identity, combined = merged.setdefault(external_id, (athlete, {}))
                if identity['displayName'] != athlete['displayName']:
                    raise ValueError('Conflicting NBA athlete identity across blocks')
                for stat, value in stats.items():
                    if stat in combined and combined[stat] != value:
                        raise ValueError('Conflicting NBA stat across blocks')
                    combined[stat] = value
    for external_id, (athlete, stats) in merged.items():
        for stat, keys in COMBOS.items():
            if all(k in stats for k in keys):
                stats[stat] = sum(stats[k] for k in keys)
        yield external_id, athlete, stats


async def sync_nba_results(db, limit=20, *, game_ids=None, refresh=False):
    from src.ingest.result_repair import sync_results
    async def fetch(client, event_id):
        response = await client.get(get_settings().espn_base_urls['nba'] + '/summary',
                                    params={'event': event_id})
        response.raise_for_status()
        payload = response.json()
        competitions = payload.get('header', {}).get('competitions', [])
        if not any(str(c.get('id')) == event_id and
                   c.get('status', {}).get('type', {}).get('completed') is True for c in competitions):
            raise ValueError('NBA summary does not identify the requested completed game')
        teams = payload.get('boxscore', {}).get('players', [])
        if len(teams) != 2 or any(not list(participants({'boxscore': {'players': [team]}})) for team in teams):
            raise ValueError('NBA boxscore missing usable team results')
        parsed = {external: stats for external, athlete, stats in participants(payload)}
        return payload, parsed
    return await sync_results(db, 'nba', SOURCE, 'espn_event_id', fetch, limit,
                              game_ids=game_ids, refresh=refresh)
