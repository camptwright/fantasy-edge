"""Fail-closed eligibility shared by advice, pricing and forecast capture."""
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from src.models.facts import QuoteAvailability

TTL_SECONDS = 2700


async def confirm_quote(db, kind, quote, event_binding=None):
    now = datetime.now(timezone.utc)
    await db.execute(insert(QuoteAvailability).values(kind=kind, quote_id=quote.id,
        source=quote.source, seen_at=now, available=True, event_binding=event_binding).on_conflict_do_update(
            index_elements=['kind', 'quote_id'], set_={'seen_at': now, 'available': True, 'event_binding': event_binding}))


async def withdraw_absent_props(db, source, poll_started):
    # Only called after a complete successful full-source snapshot. Failed
    # polls do not mark offers absent; the freshness timeout still applies.
    await db.execute(update(QuoteAvailability).where(QuoteAvailability.kind == 'prop',
        QuoteAvailability.source == source, QuoteAvailability.seen_at < poll_started)
        .values(available=False))


async def availability(db, kind, ids):
    if not ids:
        return {}
    return {row.quote_id: row for row in (await db.scalars(select(QuoteAvailability).where(
        QuoteAvailability.kind == kind, QuoteAvailability.quote_id.in_(ids)))).all()}


def exclusion(game, quote, seen, now=None):
    now = now or datetime.now(timezone.utc)
    if game is None:
        return 'unlinked_event'
    if game.game_time is None:
        return 'unknown_start_time'
    if game.status != 'scheduled' or game.game_time <= now:
        return 'event_not_pregame'
    if seen is None:
        return 'availability_unverified'
    if not seen.available:
        return 'offer_withdrawn'
    age = (now-seen.seen_at).total_seconds()
    if age < 0 or age > TTL_SECONDS:
        return 'offer_stale'
    if quote.observed_at > now:
        return 'invalid_quote_time'
    return None
