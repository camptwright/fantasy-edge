"""Read-only, bounded concurrent checks; empty props never count as validation.

Run inside the API container: python -m scripts.validate_active_slate
No provider requests, ingestion writes, quota overrides, or timestamp changes.
"""
import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import time

import httpx

SPORTS = ('nfl', 'ncaaf', 'mlb')
WARNING_MARKERS = ('Some live data is temporarily unavailable',
                   'Some calibration data is unavailable', 'Application error:')


def validate_rows(rows, kind):
    if not isinstance(rows, list):
        return ['response_not_list']
    errors = set()
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            errors.add('invalid_row')
            continue
        if row.get('id') in ids:
            errors.add('duplicate_quote')
        ids.add(row.get('id'))
        if kind == 'props' and not row.get('actionable'):
            errors.add('ineligible_live_prop')
        if row.get('actionable'):
            probability = row.get('model_probability')
            if not isinstance(probability, (float, int)) or not math.isfinite(probability) or not 0 <= probability <= 1:
                errors.add('invalid_probability')
    return sorted(errors)


async def validate(api_url, dashboard_url, rounds=5):
    if not 1 <= rounds <= 10:
        raise ValueError('rounds must be 1..10')
    limit = asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=20) as client:
        async def probe(origin, path, kind):
            async with limit:
                started = time.monotonic()
                result = {'path': path, 'kind': kind, 'errors': []}
                try:
                    async with client.stream('GET', origin+path) as response:
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 4*1024*1024:
                                raise ValueError('response_exceeds_4MiB')
                        result.update(status=response.status_code, bytes=len(body))
                        if response.status_code != 200:
                            result['errors'].append('http_error')
                        elif kind in ('props', 'signals'):
                            rows = json.loads(body)
                            result['errors'].extend(validate_rows(rows, kind))
                            if isinstance(rows, list):
                                result['actionable'] = sum(bool(r.get('actionable')) for r in rows if isinstance(r, dict))
                        elif any(marker in body.decode(errors='replace') for marker in WARNING_MARKERS):
                            result['errors'].append('partial_page')
                except (httpx.HTTPError, ValueError) as exc:
                    result['errors'].append(type(exc).__name__)
                result['seconds'] = round(time.monotonic()-started, 4)
                return result
        targets = [(api_url, f'/props/live?sport={sport}&limit=200', 'props') for sport in SPORTS]
        targets += [(api_url, f'/signals?sport={sport}', 'signals') for sport in SPORTS]
        targets += [(dashboard_url, path, 'page') for path in ('/best-bets', '/recommendations', '/calibration')]
        results = []
        for _ in range(rounds):
            results.extend(await asyncio.gather(*(probe(*target) for target in targets)))
    groups = defaultdict(list)
    for row in results:
        groups[row['path']].append(row)
    summary = {}
    for path, rows in groups.items():
        times = sorted(r['seconds'] for r in rows)
        errors = sorted({error for r in rows for error in r['errors']})
        p95 = times[math.ceil(len(times)*.95)-1]
        if p95 > 5:
            errors.append('p95_exceeds_5s')
        minimum = min((r.get('actionable', 0) for r in rows), default=0)
        summary[path] = {'requests': len(rows), 'p95_seconds': p95,
            'max_bytes': max(r.get('bytes', 0) for r in rows), 'errors': errors,
            'minimum_actionable': minimum if rows[0]['kind'] != 'page' else None,
            'status': 'failed' if errors else 'awaiting_live_quotes' if rows[0]['kind'] != 'page' and not minimum else 'passed'}
    states = {r['status'] for r in summary.values()}
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'concurrency': 3,
        'status': 'failed' if 'failed' in states else 'partial_awaiting_live_quotes' if 'awaiting_live_quotes' in states else 'passed',
        'routes': summary,
        'note': 'Point-in-time validation, not a profitability claim. Empty offer sets do not pass active-slate coverage.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-url', default='http://localhost:8000')
    parser.add_argument('--dashboard-url', default='http://fantasy-edge-grading-preview:3000')
    parser.add_argument('--rounds', type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(validate(args.api_url, args.dashboard_url, args.rounds)), indent=2))
