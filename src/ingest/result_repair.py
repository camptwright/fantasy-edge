"""Bounded retries and transactional, two-observation outcome corrections.

Old success markers do not gate this cursor. A reserved historical slice keeps
older failures moving while recent finals retain most of the fetch budget.
Missing fields never delete facts or create zeros. No forecast is rewritten.
"""
import hashlib
import asyncio
import json
import math
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert

from src.models.facts import Game, PlayerGameStat
from src.models.governance import IngestionRun, ResultCorrection, ResultSyncState
from src.models.identity import Player, PlayerExternalId

CONFIRM_AFTER = timedelta(minutes=30)


def observe(fact, pending, value, provider, event_id, digest, now):
    """Pure correction state transition; caller persists fact and ledger atomically."""
    if pending is not None and (pending.old_value != fact.value or pending.new_value != value):
        pending.status = 'superseded'
        pending.last_seen_at = now
        pending.last_payload_hash = digest
        pending = None
    if fact.value == value:
        return None, False
    if pending is None:
        return ResultCorrection(stat_id=fact.id, provider=provider, event_id=event_id,
            old_value=fact.value, new_value=value, first_seen_at=now, last_seen_at=now,
            status='pending', first_payload_hash=digest, last_payload_hash=digest), False
    pending.last_seen_at = now
    pending.last_payload_hash = digest
    if now - pending.first_seen_at >= CONFIRM_AFTER:
        fact.value = value
        pending.status = 'applied'
        pending.applied_at = now
        return pending, True
    return pending, False


async def reconcile(db, game, provider, event_id, parsed, digest, now):
    # Validate the entire parsed observation before writing any fact.
    if not parsed or not any(parsed.values()):
        raise ValueError('empty participant results')
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
           for values in parsed.values() for value in values.values()):
        raise ValueError('nonfinite result')
    identities = dict((await db.execute(select(PlayerExternalId.external_id, Player.id)
        .join(Player, Player.id == PlayerExternalId.player_id).where(
            Player.sport == game.sport, PlayerExternalId.source == provider,
            PlayerExternalId.external_id.in_(parsed)))).all())
    missing = sorted(parsed.keys() - identities.keys())
    facts = {(r.player_id, r.stat_type): r for r in (await db.scalars(
        select(PlayerGameStat).where(PlayerGameStat.game_id == game.id).with_for_update())).all()}
    pending = {(r.stat_id, r.provider): r for r in (await db.scalars(select(ResultCorrection)
        .join(PlayerGameStat, PlayerGameStat.id == ResultCorrection.stat_id).where(
            PlayerGameStat.game_id == game.id, ResultCorrection.status == 'pending'))).all()}
    rows, applied, waiting = [], 0, 0
    for external_id, values in parsed.items():
        player_id = identities.get(external_id)
        if player_id is None:
            continue
        for stat, value in values.items():
            fact = facts.get((player_id, stat))
            if fact is None:
                rows.append(dict(player_id=player_id, game_id=game.id, stat_type=stat, value=value))
                continue
            proposal, changed = observe(fact, pending.get((fact.id, provider)), value,
                                        provider, event_id, digest, now)
            if proposal is not None:
                db.add(proposal)
                waiting += proposal.status == 'pending'
            applied += changed
    written = 0
    if rows:
        result = await db.execute(insert(PlayerGameStat).values(rows).on_conflict_do_nothing(
            index_elements=['player_id', 'game_id', 'stat_type']).returning(PlayerGameStat.id))
        written = len(result.all())
    return dict(rows_written=written, corrections_applied=applied,
                corrections_pending=waiting, unmapped_players=len(missing), missing_ids=missing[:50])


async def due_games(db, sport, provider, event_column, limit, now):
    cutoff = now - timedelta(days=14)
    base = select(Game).outerjoin(ResultSyncState, and_(ResultSyncState.game_id == Game.id,
        ResultSyncState.provider == provider)).where(Game.sport == sport, Game.status == 'final',
        or_(Game.game_type.is_(None), Game.game_type != 'PRE'),
        event_column.isnot(None), or_(ResultSyncState.game_id.is_(None), ResultSyncState.next_attempt_at <= now))
    # Unknown kickoff rows remain visible in the historical/review queue.
    order = (ResultSyncState.last_attempt_at.asc().nulls_first(), Game.game_time.desc().nulls_last(), Game.id)
    reserve = max(1, limit // 4) if limit > 1 else 0
    recent = (await db.scalars(base.where(or_(Game.game_time.is_(None), Game.game_time >= cutoff),
        Game.game_time.isnot(None)).order_by(*order).limit(limit-reserve))).all()
    older = (await db.scalars(base.where(or_(Game.game_time.is_(None), Game.game_time < cutoff))
        .order_by(*order).limit(limit-len(recent)))).all()
    return recent + older


async def sync_results(db, sport, provider, event_field, fetch, limit=20, *, game_ids=None, refresh=False, prepare=None):
    if not 1 <= limit <= 50:
        raise ValueError('result batch limit must be 1..50')
    if refresh and game_ids is None:
        raise ValueError('refresh requires explicit game IDs')
    now = datetime.now(timezone.utc)
    if game_ids is not None:
        if len(game_ids) > limit:
            raise ValueError('explicit batch exceeds limit')
        games = (await db.scalars(select(Game).where(Game.id.in_(game_ids), Game.sport == sport,
            or_(Game.game_type.is_(None), Game.game_type != 'PRE'),
            Game.status == 'final', getattr(Game, event_field).isnot(None)).order_by(Game.game_time, Game.id))).all()
    else:
        games = await due_games(db, sport, provider, getattr(Game, event_field), limit, now)
    totals = dict(games=0, rows_written=0, deferred=0, unmapped_players=0,
                  corrections_pending=0, corrections_applied=0)
    # IDs only: per-game rollback must not expire objects used by later games.
    game_ids = [g.id for g in games]
    await db.commit()
    async with httpx.AsyncClient(timeout=15) as client:
        for game_id in game_ids:
            # Serialize all repaired writers per game; skip concurrent jobs.
            game = await db.scalar(select(Game).where(Game.id == game_id).with_for_update(skip_locked=True))
            if game is None:
                await db.rollback()
                continue
            state = await db.get(ResultSyncState, (game_id, provider))
            now = datetime.now(timezone.utc)
            if not refresh and state is not None and state.next_attempt_at > now:
                await db.rollback()
                continue
            event_id = str(getattr(game, event_field))
            result = {}
            try:
                async with db.begin_nested():
                    if game.game_time is None or game.game_time > now or game.status != 'final':
                        raise ValueError('unverified game time/status')
                    payload, parsed = await fetch(client, event_id)
                    if prepare is not None:
                        await prepare(db, client, payload, parsed)
                    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
                    from src.ingest.result_identities import seed_participants
                    from src.scheduler.calibration import archive
                    seeded = await seed_participants(db, sport, provider, payload, parsed)
                    evidence_path = archive('result-observations', {'provider': provider,
                        'game_id': str(game.id), 'event_id': event_id, 'observed_at': now.isoformat(),
                        'payload_hash': digest, 'payload': payload})
                    result = await reconcile(db, game, provider, event_id, parsed, digest, now)
                    result.update(identities_seeded=seeded, evidence_archive=str(evidence_path))
                status = 'partial' if result['unmapped_players'] else ('confirming' if result['corrections_pending'] else 'succeeded')
                detail = json.dumps(result, sort_keys=True)
            except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
                # Savepoint rolled back all writes from this observation. Do not
                # expose HTTP URLs/credentials, nor abort the remaining games.
                status = 'deferred'
                detail = json.dumps({'error_type': type(exc).__name__,
                    'http_status': exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None})
            if state is None:
                state = ResultSyncState(game_id=game_id, provider=provider, attempts=0)
                db.add(state)
            state.attempts += 1
            state.last_attempt_at = now
            state.status, state.detail = status, detail
            # Partial/failed fetches remain retryable indefinitely with pacing;
            # old successful games are checked weekly for late corrections.
            delay = timedelta(hours=1)
            if status == 'succeeded':
                delay = timedelta(hours=6) if game.game_time >= now-timedelta(days=14) else timedelta(days=7)
            state.next_attempt_at = now + delay
            db.add(IngestionRun(source=f'{sport}_result_repair', started_at=now,
                finished_at=datetime.now(timezone.utc), status=status,
                rows_written=result.get('rows_written', 0),
                detail=json.dumps({'game_id': str(game_id), 'event_id': event_id, 'result': json.loads(detail)})))
            await db.commit()
            await asyncio.sleep(0.25)
            totals['games'] += 1
            totals['deferred'] += status == 'deferred'
            for key in ('rows_written', 'unmapped_players', 'corrections_pending', 'corrections_applied'):
                totals[key] += result.get(key, 0)
    return totals
