"""Conservative sportsbook props from SGO and ParlayAPI.

DFS prices remain raw-archive-only. Disjoint bookmaker ownership avoids
duplicate offers across these feeds and the existing FanDuel collector.
No provider-reported fair/consensus price is treated as an offered price.
"""
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone

import httpx
from redis.asyncio import Redis
from sqlalchemy import select, update

from config.settings import get_settings
from src.db.client import get_worker_db
from src.ingest.lines import record_prop_line
from src.ingest.runs import record_run
from src.ingest.prop_events import match_priced_event as _match_game, event_binding
from src.ingest.theodds_props import select_player
from src.models.facts import Game, PlayerPropLine, QuoteAvailability
from src.models.identity import Player
from src.services import td_market

BOOKS = {'sgo': {'bovada', 'espnbet'},
         'parlay': {'draftkings', 'betmgm', 'caesars', 'pinnacle'}}
SGO_STATS = {'passing_yards': 'passing_yards', 'rushing_yards': 'rushing_yards',
    'receiving_yards': 'receiving_yards', 'receiving_receptions': 'receptions',
    'passing_attempts': 'passing_attempts', 'passing_completions': 'passing_completions',
    'passing_touchdowns': 'passing_touchdowns', 'passing_interceptions': 'passing_interceptions',
    'rushing_attempts': 'rushing_attempts', 'batting_hits': 'hits',
    'batting_totalBases': 'total_bases', 'pitching_strikeouts': 'strikeouts'}
PARLAY_STATS = {'player_pass_yds': 'passing_yards', 'player_passing_yards': 'passing_yards',
    'player_rush_yds': 'rushing_yards', 'player_rushing_yards': 'rushing_yards',
    'player_reception_yds': 'receiving_yards', 'player_receiving_yards': 'receiving_yards',
    'player_receptions': 'receptions', 'player_pass_tds': 'passing_touchdowns',
    'player_passing_touchdowns': 'passing_touchdowns', 'player_touchdown_passes': 'passing_touchdowns',
    'player_hits': 'hits', 'batter_hits': 'hits',
    'player_total_bases': 'total_bases', 'batter_total_bases': 'total_bases',
    'pitcher_strikeouts': 'strikeouts'}
FOOTBALL_STATS = {'passing_yards', 'rushing_yards', 'receiving_yards', 'receptions',
    'passing_attempts', 'passing_completions', 'passing_touchdowns', 'passing_interceptions',
    'rushing_attempts'}
SPORT_STATS = {'nfl': FOOTBALL_STATS, 'ncaaf': FOOTBALL_STATS,
    'mlb': {'hits', 'total_bases', 'strikeouts'},
    'nba': {'points', 'rebounds', 'assists', 'steals', 'blocks', 'turnovers',
            'three_pointers_made', 'points_rebounds_assists', 'points_rebounds',
            'points_assists', 'rebounds_assists', 'steals_blocks'},
    'nhl': {'goals', 'points', 'assists', 'shots_on_goal', 'blocked_shots', 'saves'}}
# Provider names are sport-specific: hockey "points" means goals, not points.
SGO_SPORT_STATS = {
    'nba': {'points': 'points', 'rebounds': 'rebounds', 'assists': 'assists',
        'steals': 'steals', 'blocks': 'blocks', 'turnovers': 'turnovers',
        'threePointersMade': 'three_pointers_made',
        'points+rebounds+assists': 'points_rebounds_assists',
        'points+rebounds': 'points_rebounds', 'points+assists': 'points_assists',
        'rebounds+assists': 'rebounds_assists', 'blocks+steals': 'steals_blocks'},
    'nhl': {'points': 'goals', 'goals+assists': 'points', 'assists': 'assists',
        'shots_onGoal': 'shots_on_goal', 'blocks': 'blocked_shots', 'goalie_saves': 'saves'},
}
PROVIDER_SPORTS = {'sgo': tuple(SPORT_STATS), 'parlay': ('nfl', 'ncaaf', 'mlb')}
PARLAY_WINDOW = timedelta(hours=2)
SLOT_GAP = timedelta(minutes=45)   # kickoffs this close share one capture
SLOT_CALLS = 3                     # calls per NFL slot while later slots still need one


def kickoff_slots(times):
    """Group kickoff times into slots: a capture shortly before a slot covers every game in it."""
    slots = []
    for t in sorted(times):
        if not slots or t - slots[-1][-1] > SLOT_GAP:
            slots.append([t])
        else:
            slots[-1].append(t)
    return [s[0] for s in slots]


def parlay_allowed(sport, now, slots, slot_calls, calls_left):
    """Spend ParlayAPI's small daily budget on NFL kickoff slots first (2026-10-11: the budget went on
    MLB and one London game, leaving the Sunday slate uncaptured). Every NFL slot later in the UTC
    budget day keeps one call in reserve; other sports only use what is left over."""
    if calls_left < 1:
        return False
    current = [s for s in slots if now < s <= now + PARLAY_WINDOW]
    later = [s for s in slots if s > now + PARLAY_WINDOW and slot_calls.get(s.isoformat(), 0) == 0]
    if sport == 'nfl':
        if not current:
            return False
        used = slot_calls.get(current[0].isoformat(), 0)
        return calls_left - 1 >= len(later) and (used < SLOT_CALLS or not later)
    pending = later + [s for s in current if slot_calls.get(s.isoformat(), 0) == 0]
    return calls_left - 1 >= len(pending)


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def price(value):
    try:
        number = float(value)
        return int(number) if math.isfinite(number) and number.is_integer() and abs(number) >= 100 else None
    except (TypeError, ValueError):
        return None


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def valid(row, now):
    return (row['updated'] is not None and 0 <= (now-row['updated']).total_seconds() <= 900
            and row['line'] is not None and row['over'] is not None and row['under'] is not None)


def parse_sgo(payload, sport, now):
    rows = []
    if not isinstance(payload, dict) or payload.get('success') is not True or not isinstance(payload.get('data'), list):
        raise ValueError('SGO response schema invalid')
    for event in payload['data']:
        if event.get('leagueID') != sport.upper() or event.get('status', {}).get('started') is not False:
            continue
        teams, status = event.get('teams', {}), event.get('status', {})
        fixture = {'home_team': teams.get('home', {}).get('names', {}).get('long'),
                   'away_team': teams.get('away', {}).get('names', {}).get('long'),
                   'commence_time': status.get('startsAt')}
        odds = event.get('odds', {})
        for odd in odds.values():
            raw_stat = odd.get('statID')
            stat = SGO_SPORT_STATS.get(sport, SGO_STATS).get(raw_stat)
            if (stat is None or odd.get('periodID') != 'game' or
                    odd.get('betTypeID') != 'ou' or odd.get('sideID') != 'over'):
                continue
            # Generic/batter strikeouts are never mapped to pitcher strikeouts.
            if stat not in SPORT_STATS[sport]:
                continue
            player = event.get('players', {}).get(odd.get('playerID'), {})
            other = odds.get(odd.get('opposingOddID'), {})
            if (other.get('sideID') != 'under' or other.get('playerID') != odd.get('playerID')
                    or other.get('statID') != raw_stat or other.get('periodID') != 'game'
                    or other.get('betTypeID') != 'ou'):
                continue
            for book in BOOKS['sgo']:
                over = odd.get('byBookmaker', {}).get(book, {})
                under = other.get('byBookmaker', {}).get(book, {})
                if over.get('available') is not True or under.get('available') is not True:
                    continue
                times = [stamp(over.get('lastUpdatedAt')), stamp(under.get('lastUpdatedAt'))]
                if any(t is None or t > now for t in times):
                    continue
                line = number(over.get('overUnder'))
                if line != number(under.get('overUnder')):
                    continue
                row = {'event': fixture, 'name': player.get('name'), 'stat': stat, 'book': book,
                       'line': line, 'over': price(over.get('odds')), 'under': price(under.get('odds')),
                       'updated': min(times)}
                if valid(row, now):
                    rows.append(row)
    return rows


def parse_parlay(payload, sport, now):
    if not isinstance(payload, list):
        raise ValueError('Parlay response schema invalid')
    rows = []
    for item in payload:
        stat = PARLAY_STATS.get(item.get('market_key'))
        if (item.get('bookmaker') not in BOOKS['parlay'] or stat not in SPORT_STATS[sport]
                or item.get('is_dfs_flat_payout') is not False or item.get('dfs_normalized') is not False
                or item.get('commence_time_reported') is not True):
            continue
        row = {'event': item, 'name': item.get('player'), 'stat': stat, 'book': item['bookmaker'],
               'line': number(item.get('line')), 'over': price(item.get('over_price')),
               'under': price(item.get('under_price')), 'updated': stamp(item.get('last_update'))}
        if valid(row, now):
            rows.append(row)
    return rows


async def reserve(redis, provider, sport, cost, daily_limit, now):
    # One atomic reservation protects concurrent workers and failed attempts.
    # Rolling account limits remain provider-enforced; no auto-upgrades.
    return bool(await redis.eval('''
        if redis.call('exists', KEYS[1]) == 1 then return 0 end
        local used = tonumber(redis.call('get', KEYS[2]) or '0')
        if used + tonumber(ARGV[1]) > tonumber(ARGV[2]) then return 0 end
        redis.call('set', KEYS[1], '1', 'EX', 1500)
        redis.call('incrby', KEYS[2], ARGV[1])
        redis.call('expire', KEYS[2], 172800)
        return 1''', 2, f'aggregate:{provider}:pace:{sport}',
        f'aggregate:{provider}:spent:{now:%Y-%m-%d}', cost, daily_limit))


async def fetch(redis, settings, provider, sport, now):
    key = settings.sportsgameodds_api_key if provider == 'sgo' else settings.parlay_api_key
    if not key:
        return None
    if await redis.exists(f'aggregate:{provider}:blocked'):
        return None
    cost = 1 if provider == 'sgo' else 3
    ceiling = settings.sportsgameodds_daily_objects if provider == 'sgo' else settings.parlay_daily_credits
    if not await reserve(redis, provider, sport, cost, ceiling, now):
        return None
    if provider == 'sgo':
        url = 'https://api.sportsgameodds.com/v2/events'
        params = {'leagueID': sport.upper(), 'oddsAvailable': 'true', 'started': 'false',
                  'limit': 1, 'includeAltLines': 'false',
                  'startsAfter': now.isoformat(), 'startsBefore': (now+timedelta(hours=24)).isoformat(),
                  'bookmakerID': ','.join(sorted(BOOKS[provider]))}
    else:
        url = f'https://parlay-api.com/v1/sports/{settings.odds_api_sport_keys[sport]}/props'
        # A page costs three credits whatever its markets or rows (parlay-api.com/docs), and a
        # whole NFL week is about 750 rows, so anytime-TD research prices ride along for free.
        markets = [k for k, v in PARLAY_STATS.items() if v in SPORT_STATS[sport]]
        params = {'bookmakers': ','.join(sorted(BOOKS[provider])), 'maxAgeSec': 900,
                  'markets': ','.join(markets + ([td_market.MARKET] if sport == 'nfl' else [])),
                  'limit': 5000, 'dfsOdds': 'effective'}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers={'x-api-key': key}, params=params)
    except httpx.RequestError:
        raise RuntimeError(f'{provider} transport failure') from None
    telemetry = {'checked_at': now.isoformat(), 'http_status': response.status_code,
                 'last_request_cost': response.headers.get('x-requests-last'),
                 'remaining': response.headers.get('x-requests-remaining'),
                 'has_more': response.headers.get('x-result-has-more')}
    await redis.set(f'aggregate:{provider}:status', json.dumps(telemetry))
    if response.status_code in (401, 402, 403, 429):
        await redis.set(f'aggregate:{provider}:blocked', str(response.status_code), ex=86400)
    if response.status_code != 200:
        raise RuntimeError(f'{provider} HTTP {response.status_code}')
    return response.json()


async def ingest(db, provider, sport, payload, now):
    parsed = (parse_sgo if provider == 'sgo' else parse_parlay)(payload, sport, now)
    # Different thresholds cannot compete for the schema's single main-line slot.
    counts = Counter((r['book'], r['name'], r['stat'], r['event'].get('commence_time'),
                      r['event'].get('home_team'), r['event'].get('away_team')) for r in parsed)
    players = list((await db.scalars(select(Player).where(Player.sport == sport))).all())
    written = parked = 0
    reasons = Counter()
    for row in parsed:
        identity = (row['book'], row['name'], row['stat'], row['event'].get('commence_time'),
                    row['event'].get('home_team'), row['event'].get('away_team'))
        if counts[identity] != 1:
            parked += 1
            reasons['competing_main_lines'] += 1
            continue
        kickoff = stamp(row['event'].get('commence_time'))
        if kickoff is None or not now < kickoff <= now+timedelta(hours=24):
            parked += 1
            reasons['outside_pregame_window_or_unknown_time'] += 1
            continue
        game = await _match_game(db, row['event'], sport)
        player = select_player(players, row['name'], game) if game else None
        # Match the provider's explicit fixture and a unique canonical sport/name.
        # select_player rejects a conflicting current team when one is recorded;
        # existing canonical players frequently have no current_team_id.
        if (not game or game.status != 'scheduled' or not game.game_time or game.game_time <= now
                or player is None):
            parked += 1
            reasons['unmatched_game_or_player_or_not_scheduled'] += 1
            continue
        source = f'{provider}_{row["book"]}'
        latest = await db.scalar(select(PlayerPropLine).where(PlayerPropLine.player_id == player.id,
            PlayerPropLine.game_id == game.id, PlayerPropLine.source == source,
            PlayerPropLine.stat_type == row['stat']).order_by(
                PlayerPropLine.observed_at.desc(), PlayerPropLine.id.desc()).limit(1))
        if latest:
            previous = await db.get(QuoteAvailability, ('prop', latest.id))
            if previous and row['updated'] <= previous.seen_at:
                continue
        if await record_prop_line(db, player_id=player.id, game_id=game.id,
            stat_type=row['stat'], line=row['line'], over_price_american=row['over'],
            under_price_american=row['under'], source=source, event_binding=event_binding(game)):
            written += 1
        current = await db.scalar(select(PlayerPropLine).where(PlayerPropLine.player_id == player.id,
            PlayerPropLine.game_id == game.id, PlayerPropLine.source == source,
            PlayerPropLine.stat_type == row['stat']).order_by(
                PlayerPropLine.observed_at.desc(), PlayerPropLine.id.desc()).limit(1))
        # Keep observed_at as our actual first observation (no retrospective leakage).
        # Availability ages from the older of the two source price timestamps.
        await db.execute(update(QuoteAvailability).where(QuoteAvailability.kind == 'prop',
            QuoteAvailability.quote_id == current.id).values(seen_at=row['updated']))
    return {'parsed': len(parsed), 'written': written, 'parked': parked,
            'parked_reasons': dict(reasons)}


async def ingest_then_archive(db, provider, sport, payload):
    """Ingest first: the call is already paid for, and a raw-archive failure (2026-10-11: disk full)
    must not discard its prices."""
    from src.scheduler.calibration import archive
    async with db.begin_nested():
        result = await ingest(db, provider, sport, payload, datetime.now(timezone.utc))
    if provider == 'parlay' and sport == 'nfl':
        try:
            result.update(await td_market.capture(db, sport, payload, datetime.now(timezone.utc)))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            result['td_error'] = f'{type(exc).__name__}: {exc}'[:200]
    try:
        archive('aggregate-props', {'provider': provider, 'sport': sport,
            'received_at': datetime.now(timezone.utc).isoformat(), 'payload': payload})
    except OSError as exc:
        result['archive_error'] = f'{type(exc).__name__}: {exc}'[:200]
    return result


async def parlay_budget(db, redis, settings, now):
    """NFL kickoff slots left in today's UTC budget day, calls spent per slot, and calls left."""
    end = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)
    times = (await db.scalars(select(Game.game_time).where(Game.sport == 'nfl', Game.status == 'scheduled',
        Game.game_time.is_not(None), Game.game_time > now, Game.game_time < end))).all()
    slots = kickoff_slots(times)
    counts = await redis.mget([f'aggregate:parlay:slot:{s.isoformat()}' for s in slots]) if slots else []
    spent = int(await redis.get(f'aggregate:parlay:spent:{now:%Y-%m-%d}') or 0)
    return slots, {s.isoformat(): int(c or 0) for s, c in zip(slots, counts)}, (settings.parlay_daily_credits - spent) // 3


async def collect():
    settings = get_settings()
    if not settings.aggregate_props_enabled:
        return {'status': 'disabled'}
    output = {}
    async with Redis.from_url(settings.redis_url, decode_responses=True) as redis:
        async with redis.lock('aggregate:collection', timeout=600, blocking_timeout=0):
            for provider in ('sgo', 'parlay'):
                for sport in PROVIDER_SPORTS[provider]:
                    now = datetime.now(timezone.utc)
                    async with get_worker_db() as db:
                        # Known kickoff is required for paid pregame collection.
                        upcoming = await db.scalar(select(Game.id).where(Game.sport == sport,
                            Game.status == 'scheduled', Game.game_time.is_not(None),
                            Game.game_time > now, Game.game_time <= now+timedelta(
                                hours=2 if provider == 'parlay' else 12)).limit(1))
                        if not upcoming:
                            continue
                        slot = None
                        if provider == 'parlay':
                            slots, slot_calls, calls_left = await parlay_budget(db, redis, settings, now)
                            if not parlay_allowed(sport, now, slots, slot_calls, calls_left):
                                async with record_run(db, f'{provider}_{sport}_props') as run:
                                    run.detail = 'Skipped: budget reserved for NFL kickoff slots'
                                continue
                            slot = next((s for s in slots if now < s <= now + PARLAY_WINDOW), None) if sport == 'nfl' else None
                        try:
                            async with record_run(db, f'{provider}_{sport}_props') as run:
                                payload = await fetch(redis, settings, provider, sport, now)
                                if payload is None:
                                    run.detail = 'Skipped: key, quota, or pacing guard'
                                    continue
                                if slot is not None:
                                    key = f'aggregate:parlay:slot:{slot.isoformat()}'
                                    await redis.incr(key)
                                    await redis.expire(key, 172800)
                                result = await ingest_then_archive(db, provider, sport, payload)
                                run.rows_written = result['written']
                                run.detail = json.dumps(result)
                                output[f'{provider}_{sport}'] = result
                        except Exception as exc:
                            # record_run records the failure; another provider still runs.
                            output[f'{provider}_{sport}'] = {'status': 'failed', 'error_type': type(exc).__name__}
    return output
