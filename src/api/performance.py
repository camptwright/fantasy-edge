"""Bounded process-local request metrics; no query strings or user identifiers."""
from collections import defaultdict, deque
import math
import resource
import sys
import time

samples = defaultdict(lambda: deque(maxlen=200))


class PerformanceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        started, size, status = time.monotonic(), 0, 500
        async def measured(message):
            nonlocal size, status
            if message['type'] == 'http.response.start':
                status = message['status']
            elif message['type'] == 'http.response.body':
                size += len(message.get('body', b''))
            await send(message)
        try:
            await self.app(scope, receive, measured)
        finally:
            route = getattr(scope.get('route'), 'path', 'unmatched')
            # Even malformed/dynamic routes cannot grow storage without bound.
            key = route if route in samples or len(samples) < 128 else 'other'
            samples[key].append((time.monotonic()-started, size, status))


def snapshot():
    rows = {}
    for route, values in list(samples.items()):
        durations = sorted(row[0] for row in values)
        rows[route] = {
            'samples': len(values),
            'p50_ms': round(durations[math.ceil(len(values)*.50)-1]*1000, 2),
            'p95_ms': round(durations[math.ceil(len(values)*.95)-1]*1000, 2),
            'max_response_bytes': max(row[1] for row in values),
            'server_errors': sum(row[2] >= 500 for row in values),
        }
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {'scope': 'This API process; last 200 requests per route; resets on restart.',
            'peak_rss_bytes': rss if sys.platform == 'darwin' else rss*1024,
            'routes': rows}
