"""Bounded, cached reads of background research summaries; never run models on GET."""
import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from time import time


def summarize(payload, league_id, season, now):
    base = {'status': 'unavailable', 'generated_at': None, 'recipe': None,
            'requested_weeks': [], 'new_captures': 0, 'counts': [], 'blockers': [],
            'serving_promoted': False}
    if not isinstance(payload, dict) or payload.get('league_id') != league_id:
        return base
    if str(payload.get('season')) != str(season):
        return {**base, 'status': 'different_season'}
    try:
        observed = datetime.fromisoformat(payload['generated_at'])
        age = (now - observed).total_seconds()
        if age < 0: return {**base, 'status': 'invalid_timestamp'}
    except (KeyError, TypeError, ValueError):
        return base
    def counts(value):
        return [{'reason': str(k)[:120], 'count': v} for k, v in sorted(value.items())
                if type(v) is int and v >= 0][:40] if isinstance(value, dict) else []
    weeks=payload.get('requested_weeks', [])
    if not isinstance(weeks,list): weeks=[]
    return {**base, 'status': 'stale' if age > 7200 else 'current',
            'generated_at': observed.isoformat(), 'recipe': str(payload.get('recipe', 'unknown'))[:160],
            'requested_weeks': [v for v in weeks
                                if type(v) is int and 1 <= v <= 18][:18],
            'new_captures': payload.get('new_captures', 0) if type(payload.get('new_captures')) is int else 0,
            'counts': counts(payload.get('counts', payload.get('grade_counts', {}))),
            'blockers': counts(payload.get('capture_blockers', payload.get('blockers', {})))}


@lru_cache(maxsize=32)
def _read(root, league_id, bucket):
    key = hashlib.sha256(league_id.encode()).hexdigest()
    result = {}
    for name, directory in [('retention', 'fantasy-retention'),
                            ('specialists', 'fantasy-specialist-prospective')]:
        path = Path(root) / directory / 'latest' / f'{key}.json'
        try:
            if path.is_symlink() or path.stat().st_size > 131072:
                result[name] = None
            else:
                result[name] = json.loads(path.read_text())
        except (OSError, ValueError):
            result[name] = None
    return result


def latest(root, league_id, season, now=None):
    now = now or datetime.now(timezone.utc)
    raw = _read(str(root), league_id, int(time() // 30))
    return {key: summarize(value, league_id, season, now) for key, value in raw.items()}
