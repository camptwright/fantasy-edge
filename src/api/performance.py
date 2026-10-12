"""Bounded process-local request metrics; no query strings or user identifiers."""
from collections import defaultdict, deque, Counter
import math
import os
from pathlib import Path
import resource
import sys
import time
import uuid
from datetime import datetime, timezone

PROCESS_ID=uuid.uuid4().hex
STARTED_AT=datetime.now(timezone.utc).isoformat()

samples = defaultdict(lambda: deque(maxlen=200))
fantasy_reads = Counter()


def record_fantasy_read(outcome):
    # Fixed labels only: no league/player IDs and no unbounded label cardinality.
    if outcome not in {'checkpoint_hit','checkpoint_miss','custom_request','generated','generation_failed'}:
        raise ValueError('Unknown fantasy read outcome')
    fantasy_reads[outcome] += 1


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
            finished = time.monotonic()
            samples[key].append((finished-started, size, status, finished))


def current_rss_bytes():
    """Linux resident pages, not ru_maxrss's lifetime high-water mark."""
    if sys.platform != 'linux':
        return None
    try:
        return int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    except (OSError, ValueError, IndexError):
        return None


def snapshot():
    rows = {}
    now = time.monotonic()
    for route, values in list(samples.items()):
        durations = sorted(row[0] for row in values)
        rows[route] = {
            'samples': len(values),
            'p50_ms': round(durations[math.ceil(len(values)*.50)-1]*1000, 2),
            'p95_ms': round(durations[math.ceil(len(values)*.95)-1]*1000, 2),
            'max_response_bytes': max(row[1] for row in values),
            'server_errors': sum(row[2] >= 500 for row in values),
            'oldest_sample_age_seconds': round(max(0, now-values[0][3]), 2),
            'newest_sample_age_seconds': round(max(0, now-values[-1][3]), 2),
        }
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {'scope': 'This API process; last 200 requests per route; resets on restart.',
            'process_id':PROCESS_ID,'started_at':STARTED_AT,
            'peak_rss_bytes': rss if sys.platform == 'darwin' else rss*1024,
            'current_rss_bytes': current_rss_bytes(),
            'fantasy_reads':dict(fantasy_reads),
            'routes': rows}
