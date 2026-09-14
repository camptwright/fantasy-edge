"""ESPN football results with verified identities and audited corrections."""
from collections import defaultdict
from config.settings import get_settings
from src.ingest.ncaaf_composites import composite_values
from src.ingest.ncaaf_player_stats import _STAT_MAP, _number, made_attempts
from src.ingest.result_repair import sync_results


def parse_boxscore(payload, event_id, *, optional_trailing_qbr=False):
    """Return merged athlete stats; reject incomplete/ambiguous supported rows."""
    competitions = payload.get('header', {}).get('competitions', [])
    teams = payload.get('boxscore', {}).get('players', [])
    if not any(str(c.get('id')) == str(event_id) and
               c.get('status', {}).get('type', {}).get('completed') is True
               for c in competitions):
        raise ValueError('event not verified final')
    if len(teams) != 2 or any(not t.get('statistics') for t in teams):
        raise ValueError('incomplete boxscore')
    players = defaultdict(dict)
    for team in teams:
        for category in team['statistics']:
            name = category.get('name')
            if name not in _STAT_MAP:
                continue
            mapping = dict(_STAT_MAP[name])
            if name == 'receiving':
                mapping['receivingTargets'] = 'targets'
            keys = category.get('keys', [])
            for entry in category.get('athletes', []):
                if entry.get('didNotPlay') is True:
                    continue
                athlete = str(entry.get('athlete', {}).get('id') or '')
                # ESPN uses negative IDs for explicitly named Team aggregates
                # (unattributed sacks/kneels/fumbles), not individual athletes.
                if (athlete.startswith('-') and athlete[1:].isdigit() and
                    str(entry.get('athlete', {}).get('displayName', '')).strip().lower() == 'team'):
                    continue
                values = entry.get('stats', [])
                omitted_qbr = (optional_trailing_qbr and name == 'passing' and keys and
                               keys[-1] == 'adjQBR' and len(values) == len(keys)-1)
                if not athlete.isdigit() or (len(keys) != len(values) and not omitted_qbr) or len(set(keys)) != len(keys):
                    raise ValueError('ambiguous athlete row')
                raw = dict(zip(keys, values))
                stats = {stat: _number(raw[key]) for key, stat in mapping.items() if key in raw}
                compounds = {'passing': [('completions/passingAttempts',
                    ('passing_completions', 'passing_attempts'))],
                    'kicking': [('fieldGoalsMade/fieldGoalAttempts', ('fg_made', 'fg_attempts')),
                                ('extraPointsMade/extraPointAttempts', ('xp_made', 'xp_attempts'))]}
                for key, names in compounds.get(name, []):
                    if key in raw:
                        pair = made_attempts(raw[key])
                        if pair is None:
                            raise ValueError('invalid made/attempts')
                        stats.update(zip(names, pair))
                for stat, value in stats.items():
                    if value is None or not value.is_integer() or (value < 0 and 'yards' not in stat and stat not in ('longest_rush', 'longest_reception')):
                        raise ValueError('invalid numeric outcome')
                    if stat in players[athlete] and players[athlete][stat] != value:
                        raise ValueError('conflicting repeated statistic')
                    players[athlete][stat] = value
    if not players:
        raise ValueError('empty supported boxscore')
    for values in players.values():
        values.update(composite_values(values))
    return dict(players)


async def sync_nfl_results(db, limit=40):
    return await sync_football_results(db, 'nfl', limit)


async def sync_football_results(db, sport, limit, *, game_ids=None, refresh=False):
    async def fetch(client, event_id):
        response = await client.get(get_settings().espn_base_urls[sport] + '/summary', params={'event': event_id})
        response.raise_for_status()
        payload = response.json()
        parsed = parse_boxscore(payload, event_id, optional_trailing_qbr=sport == 'ncaaf')
        from src.services.football_pbp_validation import audit
        from src.scheduler.calibration import archive
        report = audit(payload, event_id)
        archive('football-pbp-validation', {'sport': sport, **report})
        if sport == 'ncaaf':
            from src.ingest.participation import verified_reception_zeros
            evidence = verified_reception_zeros(payload, parsed)
            for row in evidence:
                parsed[row['external_id']]['receptions'] = row['value']
            payload = {**payload, '_participation_evidence': evidence}
        return payload, parsed
    kwargs = {'game_ids': game_ids} if game_ids is not None else {}
    if refresh:
        kwargs['refresh'] = True
    return await sync_results(db, sport, f'espn_{sport}', 'espn_event_id', fetch, limit, **kwargs)
