"""Redis-backed pacing and secret-free provider quota telemetry."""
import json
from datetime import datetime, timedelta, timezone

SEASONS = {'nfl': [1, 2, 8, 9, 10, 11, 12], 'ncaaf': [1, 8, 9, 10, 11, 12],
           'mlb': list(range(3, 12)), 'nba': [1, 2, 3, 4, 5, 6, 10, 11, 12],
           'nhl': [1, 2, 3, 4, 5, 6, 10, 11, 12]}


def apply_nfl_window(report, kickoff, now):
    """Describe the paid collector's window without spending provider credits."""
    if not report.get('nfl_props_priority'):
        return report
    for row in report['sports']:
        if row['sport'] != 'nfl':
            continue
        opens = kickoff - timedelta(hours=2) if kickoff else None
        row['next_kickoff'] = kickoff.isoformat() if kickoff else None
        row['window_opens_at'] = opens.isoformat() if opens else None
        if row['reason'] in ('due', 'paced') and (opens is None or opens > now):
            row['reason'] = 'no_scheduled_game' if opens is None else 'outside_refresh_window'
    return report


async def reserve(redis, settings, sport):
    now = datetime.now(timezone.utc)
    months = getattr(settings, 'odds_api_season_months', SEASONS)
    if now.month not in months.get(sport, []):
        return False
    interval = max(1800, int(getattr(settings, 'odds_api_poll_seconds', {}).get(sport, 86400)))
    return bool(await redis.set('odds_api:next:' + sport, now.isoformat(), nx=True, ex=interval))


async def record_headers(redis, headers, status):
    def number(name):
        value = headers.get(name)
        try:
            result = int(value)
            return result if result >= 0 else None
        except (TypeError, ValueError):
            return None
    payload = {'observed_at': datetime.now(timezone.utc).isoformat(), 'http_status': status,
        'remaining': number('x-requests-remaining'), 'used': number('x-requests-used'),
        'last_request_cost': number('x-requests-last')}
    await redis.set('odds_api:quota_status', json.dumps(payload))
    return payload


async def status(redis, settings):
    raw = await redis.get('odds_api:quota_status')
    telemetry = json.loads(raw) if raw else {}
    blocked = bool(await redis.exists('odds_api:quota_exhausted'))
    months = getattr(settings, 'odds_api_season_months', SEASONS)
    sports = []
    priority = getattr(settings, 'odds_api_nfl_props_priority', False)
    for sport in settings.supported_sports:
        ttl = await redis.ttl('odds_api:next:' + sport)
        active = datetime.now(timezone.utc).month in months.get(sport, [])
        reason = 'not_configured' if not settings.odds_api_key else 'quota_guard' if blocked else 'offseason' if not active else 'paced' if ttl > 0 else 'due'
        if priority and sport != 'nfl':
            reason = 'paused_for_nfl_props'
        sports.append({'sport': sport, 'reason': reason, 'cooldown_seconds': max(0, ttl),
            'interval_seconds': 1800 if priority and sport == 'nfl' else max(1800, int(getattr(settings, 'odds_api_poll_seconds', {}).get(sport, 86400)))})
    return {'configured': bool(settings.odds_api_key), 'quota_blocked': blocked,
        'quota_retry_in_seconds': max(0, await redis.ttl('odds_api:quota_exhausted')),
        'quota_floor': settings.odds_api_quota_floor, 'telemetry': telemetry, 'sports': sports,
        'nfl_props_priority': priority,
        'note': ('NFL props priority: four markets from FanDuel, nearest event only, every 30 minutes within two hours of kickoff while budget allows. Other Odds API polling paused. ' if priority else 'Daily default per active sport. ') + 'Credits are last observed, not a live balance. Guard expiry permits a retry; it does not indicate a provider quota reset.'}
