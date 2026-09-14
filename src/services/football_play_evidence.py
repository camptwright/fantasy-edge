"""Strictly scoped ESPN per-play statistic evidence, not cumulative splits."""
import math
from urllib.parse import urlparse

FIELDS = {
    'passing': {'passingYards': 'passing_yards', 'completions': 'passing_completions',
                'passingAttempts': 'passing_attempts', 'passingTouchdowns': 'passing_touchdowns'},
    'rushing': {'rushingYards': 'rushing_yards', 'rushingAttempts': 'rushing_attempts',
                'rushingTouchdowns': 'rushing_touchdowns'},
    'receiving': {'receivingYards': 'receiving_yards', 'receptions': 'receptions',
                  'receivingTouchdowns': 'receiving_touchdowns'},
}


def scoped_url(url, path):
    ref = urlparse(url)
    if ref.scheme not in ('http', 'https') or ref.netloc != 'sports.core.api.espn.com' or ref.path != path:
        raise ValueError('wrong evidence scope')
    return 'https://sports.core.api.espn.com' + ref.path


def parse_evidence(payload, league, event, play, athlete, category):
    base = f'/v2/sports/football/leagues/{league}/events/{event}/competitions/{event}/plays/{play}'
    scoped_url(payload['$ref'], base + f'/participants/{athlete}/statistics/0')
    scoped_url(payload['play']['$ref'], base)
    split = payload['splits']
    if str(split['id']) != '0' or split['name'] != 'play':
        raise ValueError('not per-play evidence')
    categories = [x for x in split['categories'] if x['name'] == category]
    if len(categories) != 1:
        raise ValueError('missing or duplicated stat category')
    values = {}
    for stat in categories[0]['stats']:
        if stat['name'] not in FIELDS[category]:
            continue
        key = FIELDS[category][stat['name']]
        value = stat['value']
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not float(value).is_integer()
                or (value < 0 and 'yards' not in key) or key in values):
            raise ValueError('invalid or duplicated play stat')
        values[key] = int(value)
    if set(values) != set(FIELDS[category].values()):
        raise ValueError('incomplete play stat category')
    return values
