"""Bounded, restartable official MLB boxscore backfill for completed games.

Only actual participant game stats are stored. No season totals or missing
fields become player outcomes. This does not infer sportsbook DNP/void rules.
"""
import math
from config.settings import get_settings
from src.ingest.result_repair import sync_results

BAT = {'plateAppearances': 'plate_appearances', 'hits': 'hits', 'runs': 'runs', 'rbi': 'rbis', 'totalBases': 'total_bases',
       'homeRuns': 'home_runs', 'doubles': 'doubles', 'triples': 'triples',
       'stolenBases': 'stolen_bases', 'strikeOuts': 'batter_strikeouts', 'baseOnBalls': 'batter_walks'}
PITCH = {'strikeOuts': 'strikeouts', 'baseOnBalls': 'walks_allowed', 'hits': 'hits_allowed',
         'earnedRuns': 'earned_runs_allowed', 'outs': 'pitching_outs', 'gamesStarted': 'pitching_games_started'}


def valid_count(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 and float(value).is_integer()


def player_results(payload):
    for side in ('home', 'away'):
        for person in payload.get('teams', {}).get(side, {}).get('players', {}).values():
            external_id = person.get('person', {}).get('id')
            if external_id is None:
                continue
            stats = person.get('stats', {})
            for category, mapping in [('batting', BAT), ('pitching', PITCH)]:
                values = stats.get(category, {})
                # Bench players often carry seasonStats but no game participation.
                if not values.get('gamesPlayed', 0):
                    continue
                for field, stat in mapping.items():
                    value = values.get(field)
                    if value is not None and not valid_count(value):
                        raise ValueError('invalid MLB outcome')
                    if valid_count(value):
                        yield str(external_id), stat, float(value)
                if category == 'batting':
                    fields = ('hits', 'runs', 'rbi')
                    if all(valid_count(values.get(f)) for f in fields):
                        yield str(external_id), 'hits_runs_rbis', float(sum(values[f] for f in fields))
                    fields = ('hits', 'doubles', 'triples', 'homeRuns')
                    if all(valid_count(values.get(f)) for f in fields):
                        singles = values['hits']-sum(values[f] for f in fields[1:])
                        if singles >= 0:
                            yield str(external_id), 'singles', float(singles)


async def sync_mlb_results(db, limit=20, *, game_ids=None, refresh=False):
    async def fetch(client, event_id):
        base = get_settings().mlb_stats_api_base_url
        status = await client.get(f'{base}/schedule', params={'sportId': 1, 'gamePk': event_id})
        status.raise_for_status()
        schedule = status.json()
        if not any(str(g.get('gamePk')) == event_id and g.get('status', {}).get('abstractGameState') == 'Final'
                   for day in schedule.get('dates', []) for g in day.get('games', [])):
            raise ValueError('MLB event not verified final')
        response = await client.get(f'{base}/game/{event_id}/boxscore')
        response.raise_for_status()
        payload = response.json()
        if not all(payload.get('teams', {}).get(side, {}).get('players') for side in ('home', 'away')):
            raise ValueError('incomplete official boxscore')
        parsed = {}
        for external, stat, value in player_results(payload):
            values = parsed.setdefault(external, {})
            if stat in values and values[stat] != value:
                raise ValueError('conflicting MLB statistic')
            values[stat] = value
        return {'schedule': schedule, 'boxscore': payload}, parsed
    kwargs = {'game_ids': game_ids} if game_ids is not None else {}
    if refresh:
        kwargs['refresh'] = True
    return await sync_results(db, 'mlb', 'mlb_stats_api', 'mlb_game_pk', fetch, limit, **kwargs)
