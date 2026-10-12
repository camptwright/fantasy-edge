"""Bounded local-only mixed-load check: checkpoint GETs and non-mutating trades.

No ingestion, model builds, provider calls or transactions. Run in preview API.
At most 30 rounds, six concurrent requests per round; never auto-retry 429s.
"""
import json
import math
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from config.settings import get_settings


def main():
    token = get_settings().fantasy_api_token
    def call(path, payload=None):
        start = time.perf_counter()
        req = Request('http://127.0.0.1:8000' + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
        try:
            try: response = urlopen(req, timeout=5)
            except HTTPError as exc: response = exc
            with response:
                body = json.load(response)
                return response.code, (time.perf_counter()-start)*1000, body
        except Exception as exc:
            return 0, (time.perf_counter()-start)*1000, {'status': type(exc).__name__}
    code, _, leagues = call('/api/v2/fantasy/leagues')
    assert code == 200
    paths = ['/api/v2/fantasy/leagues/'+quote(l['league_id'], safe='')
             for l in leagues['items'] if l['sport']=='nfl'][:3]
    assert paths
    observations = []
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=6) as pool:
        for _ in range(30):
            code, elapsed, overview = call(paths[0]+'/overview')
            observations.append(('overview', code, elapsed, overview.get('status')))
            owners = {}
            for p in overview.get('comparison_players', []):
                if p.get('roster_id') and p['ownership'] in ('your_roster','other_roster'):
                    owners.setdefault(p['roster_id'], p['player_id'])
            package = list(owners.values())[:2]
            jobs = [('overview', pool.submit(call, path+'/overview')) for path in paths]
            if code == 200 and overview.get('status') == 'snapshot_available' and len(package)==2:
                payload = {'generated_at': overview['generated_at'], 'side_a':package[:1], 'side_b':package[1:]}
                jobs += [('trade', pool.submit(call, paths[0]+'/trade-preview', payload)) for _ in range(3)]
            for kind, future in jobs:
                status, ms, body = future.result()
                observations.append((kind,status,ms,body.get('status') or body.get('detail')))
            if any(status == 0 or status >= 500 for _,status,_,_ in observations):
                break  # Stop on transport/server errors; don't amplify an incident.
            time.sleep(1)
    report = {'elapsed_seconds':round(time.perf_counter()-start,2), 'max_concurrency':6,
              'scope':'preview loopback API; not browser navigation, production capacity, or long-term SLO', 'results':{}}
    for kind in ('overview','trade'):
        rows=[r for r in observations if r[0]==kind]
        groups={}
        for status in sorted({r[1] for r in rows}):
            values=sorted(r[2] for r in rows if r[1]==status)
            groups[str(status)]={'count':len(values), 'p50_ms':round(values[math.ceil(len(values)*.5)-1],2),
                'p95_ms':round(values[math.ceil(len(values)*.95)-1],2),'max_ms':round(max(values),2)}
        report['results'][kind]={'by_http_status':groups,'outcomes':dict(Counter(str(r[3]) for r in rows))}
    print(json.dumps(report,indent=2))
    if any(status == 0 or status >= 500 for _,status,_,_ in observations): raise SystemExit(1)


if __name__ == '__main__': main()
