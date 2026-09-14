"""Opt-in, budget-limited current NFL props; no historical or unguarded calls.

One bookmaker, four markets, one nearest event per poll. Scheduled polling
only runs during the last two hours before kickoff. Names without a unique
canonical NFL match are parked, never assigned a fabricated provider ID.
"""
import json
import math
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, text, update

from config.settings import get_settings
from src.ingest.lines import record_prop_line
from src.ingest.runs import record_run
from src.ingest.theodds import _match_game, is_quota_exhausted, set_quota_exhausted
from src.models.facts import Game, PlayerPropLine, QuoteAvailability
from src.models.identity import Player
from src.services.odds_pacing import record_headers, reserve
from src.services.quote_eligibility import TTL_SECONDS

MARKETS = {'player_pass_yds': 'passing_yards', 'player_rush_yds': 'rushing_yards',
           'player_reception_yds': 'receiving_yards', 'player_receptions': 'receptions'}
SOURCE = 'theodds_fanduel'


def rows_for(event, now):
    """Only paired main O/U lines from the same book, player and threshold."""
    rows = []
    for book in event.get('bookmakers', []):
        if book.get('key') != 'fanduel':
            continue
        for market in book.get('markets', []):
            stat = MARKETS.get(market.get('key'))
            try:
                updated = datetime.fromisoformat(market['last_update'].replace('Z', '+00:00'))
                age = (now - updated).total_seconds()
            except (KeyError, TypeError, ValueError):
                continue
            if not stat or not 0 <= age <= TTL_SECONDS:
                continue
            pairs = {}
            for outcome in market.get('outcomes', []):
                name, side = outcome.get('description'), outcome.get('name')
                point, price = outcome.get('point'), outcome.get('price')
                if not isinstance(name, str) or side not in ('Over', 'Under'):
                    continue
                if not isinstance(point, (float, int)) or not math.isfinite(point) or point < 0:
                    continue
                if not isinstance(price, int) or abs(price) < 100:
                    continue
                pairs.setdefault((name, float(point)), {}).setdefault(side, []).append(price)
            # Multiple thresholds for one player cannot share our main-line slot.
            counts = {}
            for name, point in pairs:
                counts[name] = counts.get(name, 0) + 1
            for (name, point), sides in pairs.items():
                if counts[name] == 1 and len(sides.get('Over', [])) == len(sides.get('Under', [])) == 1:
                    rows.append((name, stat, point, sides['Over'][0], sides['Under'][0]))
    return rows


def select_player(players, name, game):
    # Exact unique sport match only; no suffix/fuzzy match or invented IDs.
    candidates = [p for p in players if p.full_name == name]
    if len(candidates) != 1:
        return None
    player = candidates[0]
    if player.current_team_id and player.current_team_id not in (game.home_team_id, game.away_team_id):
        return None
    return player


async def _get(client, redis, settings, path, **params):
    try:
        response = await client.get(settings.odds_api_base_url + path,
            params={'apiKey': settings.odds_api_key, **params})
    except httpx.RequestError:
        raise RuntimeError('Odds API transport failure') from None
    telemetry = await record_headers(redis, response.headers, response.status_code)
    remaining = telemetry['remaining']
    if response.status_code == 429 or remaining is None or remaining < settings.odds_api_quota_floor + len(MARKETS):
        await set_quota_exhausted(redis)
    if response.status_code != 200:
        raise RuntimeError(f'Odds API request failed: {response.status_code}')
    return response.json(), remaining


async def poll_nfl_props(db, redis, *, horizon_hours=2):
    settings = get_settings()
    if not settings.odds_api_nfl_props_priority or not settings.odds_api_key:
        return 0
    now = datetime.now(timezone.utc)
    # Unknown kickoff fixtures are intentionally ineligible for paid pregame polling.
    upcoming = await db.scalar(select(Game.id).where(Game.sport == 'nfl',
        Game.status == 'scheduled', Game.game_time.is_not(None),
        Game.game_time > now, Game.game_time <= now + timedelta(hours=horizon_hours)).limit(1))
    if upcoming is None:
        return 0
    # Serialize this feed, including manual probes, before checking account telemetry.
    async with redis.lock('odds_api:props_lock', timeout=120, blocking_timeout=0):
        if await is_quota_exhausted(redis):
            return 0
        telemetry = json.loads(await redis.get('odds_api:quota_status') or '{}')
        remaining = telemetry.get('remaining')
        if remaining is None or remaining - len(MARKETS) < settings.odds_api_quota_floor:
            await set_quota_exhausted(redis)
            return 0
        # Reuse the existing season-aware guard; independent 30-minute NFL slot.
        paced = settings.model_copy(update={'odds_api_poll_seconds': {'nfl': 1800}})
        if not await reserve(redis, paced, 'nfl'):
            return 0
        async with record_run(db, 'theodds_nfl_props') as run:
            await db.execute(text("SELECT pg_advisory_xact_lock(hashtext('theodds_nfl_props'))"))
            async with httpx.AsyncClient(timeout=20) as client:
                events, remaining = await _get(client, redis, settings,
                    '/sports/americanfootball_nfl/events')
                if remaining is None or remaining - len(MARKETS) < settings.odds_api_quota_floor:
                    run.detail = 'Insufficient observed credits; no odds requested'
                    return 0
                for event in sorted(events, key=lambda e: e.get('commence_time', '')):
                    game = await _match_game(db, event, 'nfl')
                    if not game or game.status != 'scheduled' or not game.game_time or not now < game.game_time <= now + timedelta(hours=horizon_hours):
                        continue
                    payload, remaining = await _get(client, redis, settings,
                        f"/sports/americanfootball_nfl/events/{event['id']}/odds",
                        bookmakers='fanduel', markets=','.join(MARKETS), oddsFormat='american')
                    matched = await _match_game(db, payload, 'nfl')
                    if payload.get('id') != event['id'] or matched is None or matched.id != game.id:
                        raise RuntimeError('Odds API event identity mismatch')
                    players = list((await db.scalars(select(Player).where(Player.sport == 'nfl'))).all())
                    # Withdrawal is scoped to this event/book/market set, never the full feed.
                    ids = select(PlayerPropLine.id).where(PlayerPropLine.game_id == game.id,
                        PlayerPropLine.source == SOURCE, PlayerPropLine.stat_type.in_(MARKETS.values()))
                    await db.execute(update(QuoteAvailability).where(QuoteAvailability.kind == 'prop',
                        QuoteAvailability.quote_id.in_(ids)).values(available=False))
                    parked = 0
                    for name, stat, point, over, under in rows_for(payload, datetime.now(timezone.utc)):
                        player = select_player(players, name, game)
                        if player is None:
                            parked += 1
                            continue
                        if await record_prop_line(db, player_id=player.id, game_id=game.id,
                            stat_type=stat, line=point, over_price_american=over,
                            under_price_american=under, source=SOURCE):
                            run.rows_written += 1
                    run.detail = f'Four-market NFL poll; {parked} identities parked; {remaining} credits remaining'
                    return run.rows_written
            run.detail = 'No matching pregame event within horizon'
            return 0
