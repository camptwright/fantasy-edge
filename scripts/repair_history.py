"""Bounded, restartable result repair. No odds requests or Elo replay.

Example: python -m scripts.repair_history --sport mlb --season 2026 --max-games 100
Dry-run is default; --apply explicitly enables writes.
"""
import argparse
import asyncio
from datetime import datetime, timezone, timedelta, date
import json

import httpx
from sqlalchemy import select, or_, and_, text
from config.settings import get_settings
from src.db.client import get_worker_db
from src.ingest.identity import resolve_team, resolve_verified_espn_team
from src.ingest.mlb import _kickoff
from src.ingest.mlb_results import sync_mlb_results
from src.ingest.nfl_results import sync_football_results
from src.models.facts import Game
from src.models.governance import ResultSyncState
from src.scheduler.calibration import archive


def completed_mlb_games(payload, season, now):
    result = {}
    for day in payload.get('dates', []):
        for g in day.get('games', []):
            kickoff = _kickoff(g)
            if (g.get('gameType') not in ('R', 'F', 'D', 'L', 'W') or
                g.get('status', {}).get('abstractGameState') != 'Final' or
                g.get('status', {}).get('codedGameState') != 'F' or
                str(g.get('season')) != str(season) or kickoff is None or kickoff >= now):
                continue
            event = str(g.get('gamePk', ''))
            teams = g.get('teams', {})
            if not event.isdigit() or len(event) > 16 or any(
                not teams.get(s, {}).get('team', {}).get('name') or
                not isinstance(teams[s].get('score'), int) for s in ('home', 'away')):
                raise ValueError('incomplete MLB schedule identity/scores')
            # Suspended games appear on both the original and resumption day.
            # Retain original start; require identical identity and final scores.
            if g.get('resumedFrom'):
                g = {**g, 'gameDate': g['resumedFrom']}
            if event in result:
                prior = result[event]
                fields = ('season', 'gameType', 'gameDate')
                if any(prior.get(k) != g.get(k) for k in fields) or any(
                    (prior['teams'][s]['team']['id'], prior['teams'][s]['score']) !=
                    (g['teams'][s]['team']['id'], g['teams'][s]['score']) for s in ('home', 'away')):
                    raise ValueError('conflicting schedule event')
                continue
            result[event] = g
    return list(result.values())


async def discover_mlb(db, season, apply):
    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(get_settings().mlb_stats_api_base_url+'/schedule',
                                    params={'sportId': 1, 'season': season})
        response.raise_for_status()
        payload = response.json()
    games = completed_mlb_games(payload, season, now)
    existing = set((await db.scalars(select(Game.mlb_game_pk).where(Game.sport == 'mlb'))).all())
    missing = [g for g in games if str(g['gamePk']) not in existing]
    report = {'provider_final_games': len(games), 'missing_schedule_games': len(missing),
              'games_inserted': 0, 'unresolved_team_events': []}
    if not apply:
        return report
    evidence = archive('history-schedules', {'observed_at': now.isoformat(), 'season': season, 'payload': payload})
    report['evidence_archive'] = str(evidence)
    for g in missing:
        async with db.begin_nested():
            try:
                home = await resolve_team(db, g['teams']['home']['team']['name'], 'mlb')
                away = await resolve_team(db, g['teams']['away']['team']['name'], 'mlb')
            except LookupError:
                report['unresolved_team_events'].append(str(g['gamePk']))
                continue
            # Exact provider ID: never merge doubleheaders via a 24-hour window.
            from sqlalchemy.dialects.postgresql import insert
            inserted = await db.execute(insert(Game).values(sport='mlb', season=season,
                mlb_game_pk=str(g['gamePk']), game_time=_kickoff(g), status='final',
                game_type='REG' if g['gameType'] == 'R' else 'POST',
                home_team_id=home.id, away_team_id=away.id,
                home_score=g['teams']['home']['score'], away_score=g['teams']['away']['score'])
                .on_conflict_do_nothing(index_elements=['mlb_game_pk']).returning(Game.id))
            report['games_inserted'] += len(inserted.all())
        await db.commit()
    return report


async def discover_ncaaf(db, season, apply):
    """Weekly FBS schedule windows; no ratings replay or guessed team aliases."""
    now = datetime.now(timezone.utc)
    start, end = date(season, 8, 1), min(now.date(), date(season+1, 2, 1))
    events, payloads = {}, []
    async with httpx.AsyncClient(timeout=30) as client:
        while start <= end:
            stop = min(start+timedelta(days=6), end)
            response = await client.get(get_settings().espn_base_urls['ncaaf']+'/scoreboard',
                params={'dates': f'{start:%Y%m%d}-{stop:%Y%m%d}', 'groups': 80, 'limit': 1000})
            response.raise_for_status()
            payload = response.json()
            payloads.append(payload)
            for event in payload.get('events', []):
                if event.get('season', {}).get('year') != season or event.get('season', {}).get('type') not in (2, 3):
                    continue
                if not event.get('status', {}).get('type', {}).get('completed'):
                    continue
                events[str(event['id'])] = event
            start = stop+timedelta(days=1)
            await asyncio.sleep(.25)
    existing = set((await db.scalars(select(Game.espn_event_id).where(Game.sport == 'ncaaf'))).all())
    missing = {k:v for k,v in events.items() if k not in existing}
    report = {'provider_final_games': len(events), 'missing_schedule_games': len(missing),
              'games_inserted': 0, 'unresolved_team_events': []}
    if not apply:
        return report
    report['evidence_archive'] = archive('history-schedules', {'sport': 'ncaaf', 'season': season,
        'observed_at': now.isoformat(), 'payloads': payloads})
    from sqlalchemy.dialects.postgresql import insert
    for event_id, event in missing.items():
        competitions = event.get('competitions', [])
        if len(competitions) != 1 or str(competitions[0].get('id')) != event_id:
            raise ValueError('ambiguous football competition')
        sides = {c.get('homeAway'): c for c in competitions[0].get('competitors', [])}
        if set(sides) != {'home', 'away'}:
            raise ValueError('incomplete football teams')
        kickoff = datetime.fromisoformat(event['date'].replace('Z', '+00:00'))
        if kickoff.tzinfo is None or kickoff >= now:
            continue
        try:
            async with db.begin_nested():
                resolved = {}
                for side in ('home', 'away'):
                    try:
                        resolved[side] = await resolve_team(db, sides[side]['team']['id'], 'ncaaf')
                    except LookupError:
                        resolved[side] = await resolve_verified_espn_team(db, sides[side]['team'], 'ncaaf')
                home, away = resolved['home'], resolved['away']
        except ValueError:
            report['unresolved_team_events'].append({'event_id': event_id,
                'teams': [c['team'].get('displayName') for c in sides.values()]})
            continue
        inserted = await db.execute(insert(Game).values(sport='ncaaf', season=season,
            espn_event_id=event_id, game_time=kickoff, status='final', week=event.get('week', {}).get('number'),
            game_type='REG' if event['season']['type'] == 2 else 'POST',
            home_team_id=home.id, away_team_id=away.id,
            home_score=int(sides['home']['score']), away_score=int(sides['away']['score']))
            .on_conflict_do_nothing(index_elements=['espn_event_id']).returning(Game.id))
        report['games_inserted'] += len(inserted.all())
        await db.commit()
    return report


async def run(args):
    result = {'sport': args.sport, 'season': args.season, 'apply': args.apply,
              'started_at': datetime.now(timezone.utc).isoformat(), 'batches': []}
    async with get_worker_db() as guard, get_worker_db() as db:
        # Prevent overlapping manual runs; normal workers still use game locks.
        locked = await guard.scalar(text('SELECT pg_try_advisory_lock(hashtextextended(:key, 0))'),
                                 {'key': f'history-repair:{args.sport}:{args.season}'})
        if not locked:
            raise RuntimeError('history repair already running')
        try:
            if args.sport == 'mlb':
                result['schedule'] = await discover_mlb(db, args.season, args.apply)
                print(json.dumps({'schedule': result['schedule']}), flush=True)
            elif args.sport == 'ncaaf' and args.discover_football:
                result['schedule'] = await discover_ncaaf(db, args.season, args.apply)
                print(json.dumps({'schedule': result['schedule']}), flush=True)
            provider = 'mlb_stats_api' if args.sport == 'mlb' else 'espn_'+args.sport
            now = datetime.now(timezone.utc)
            query = select(Game.id).outerjoin(ResultSyncState, and_(ResultSyncState.game_id == Game.id,
                ResultSyncState.provider == provider)).where(Game.sport == args.sport, Game.season == args.season,
                Game.status == 'final', Game.game_type != 'PRE')
            if not args.refresh:
                query = query.where(or_(ResultSyncState.game_id.is_(None), ResultSyncState.next_attempt_at <= now))
            ids = (await db.scalars(query.order_by(ResultSyncState.last_attempt_at.asc().nulls_first(),
                Game.game_time.desc().nulls_last(), Game.id).limit(args.max_games))).all()
            result['eligible_games_in_budget'] = len(ids)
            await db.commit()
            if args.apply:
                for offset in range(0, len(ids), 20):
                    batch = ids[offset:offset+20]
                    if args.sport == 'mlb':
                        summary = await sync_mlb_results(db, 20, game_ids=batch, refresh=args.refresh)
                    else:
                        summary = await sync_football_results(db, args.sport, 20, game_ids=batch, refresh=args.refresh)
                    result['batches'].append(summary)
                    print(json.dumps({'completed_batch': len(result['batches']), **summary}), flush=True)
                    await asyncio.sleep(1)
        finally:
            await guard.execute(text('SELECT pg_advisory_unlock(hashtextextended(:key, 0))'),
                             {'key': f'history-repair:{args.sport}:{args.season}'})
            await guard.commit()
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    print(json.dumps({'archive': archive('history-repair', result), 'eligible_games_in_budget': result.get('eligible_games_in_budget')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sport', choices=['mlb', 'ncaaf', 'nfl'], required=True)
    parser.add_argument('--season', type=int, required=True)
    parser.add_argument('--max-games', type=int, default=100)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--refresh', action='store_true', help='Re-observe selected completed games before their normal retry time; correction confirmation still requires 30 minutes.')
    parser.add_argument('--discover-football', action='store_true', help='Discover missing NCAAF fixtures in weekly FBS windows; unresolved team aliases are reported.')
    args = parser.parse_args()
    if not 1 <= args.max_games <= 3000 or not 2000 <= args.season <= datetime.now(timezone.utc).year:
        parser.error('invalid season or game budget (1..3000)')
    asyncio.run(run(args))
