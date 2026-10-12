"""Read-only smoke check; run inside the workspace API container.

Reads the token from settings without printing it. Does not trigger ingestion,
evaluation, or checkpoint refresh. Timings are smoke samples, not a load test.
"""
import json
from time import perf_counter
from urllib.parse import quote
from urllib.request import Request, urlopen

from config.settings import get_settings


def get(path):
    start = perf_counter()
    request = Request('http://127.0.0.1:8000' + path,
                      headers={'Authorization': 'Bearer ' + get_settings().fantasy_api_token})
    with urlopen(request, timeout=5) as response:
        payload = json.load(response)
        assert response.headers.get('Cache-Control') == 'no-store'
    return payload, round((perf_counter() - start) * 1000, 2)


def main():
    ready, _ = get('/health/ready')
    assert ready['status'] == 'ready'
    leagues, elapsed = get('/api/v2/fantasy/leagues')
    report = {'leagues_ms': elapsed, 'leagues': [], 'timing_scope': 'sequential smoke samples, not load percentiles'}
    for league in leagues['items']:
        if league['sport'] != 'nfl':
            continue
        path = '/api/v2/fantasy/leagues/' + quote(league['league_id'], safe='') + '/overview'
        samples = [get(path) for _ in range(3)]
        payload = samples[-1][0]
        assert payload['schema_version'] == '2'
        assert payload['actionable'] is False
        report['leagues'].append({'league_id': league['league_id'],
            'status': payload['status'], 'starters': len(payload['starters']),
            'samples_ms': [elapsed for _, elapsed in samples]})
    performance, _ = get('/operations/performance')
    assert performance['service'] == 'workspace-preview'
    report['performance'] = performance
    runtime, _ = get('/api/v2/operations/runtime')
    report['runtime_observer'] = {'status': runtime['status'],
        'observations': len(runtime['history']), 'latest': runtime.get('latest'),
        'scope': runtime.get('scope')}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
