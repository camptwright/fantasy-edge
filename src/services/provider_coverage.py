"""Bounded quote diagnostics; never poll providers or reprice predictions."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from src.models.facts import PlayerPropLine, Game, QuoteAvailability
from src.services.quote_eligibility import exclusion


async def coverage(db):
    now=datetime.now(timezone.utc)
    rows=(await db.execute(select(PlayerPropLine,Game,QuoteAvailability)
        .outerjoin(Game,Game.id==PlayerPropLine.game_id)
        .outerjoin(QuoteAvailability,(QuoteAvailability.quote_id==PlayerPropLine.id)&(QuoteAvailability.kind=='prop'))
        .where(PlayerPropLine.observed_at>=now-timedelta(days=7))
        .order_by(PlayerPropLine.observed_at.desc(),PlayerPropLine.id).limit(20001))).all()
    groups=defaultdict(lambda:{'offers':0,'quote_eligible':0,'blockers':Counter(),'markets':set(),'last_observed_at':None,'last_confirmed_at':None})
    seen=set()
    for quote,game,available in rows[:20000]:
        key=(quote.source,quote.game_id,quote.player_id,quote.stat_type,quote.line)
        if key in seen: continue
        seen.add(key)
        group=groups[(quote.source,game.sport if game else 'unlinked')]
        group['offers']+=1
        group['markets'].add(quote.stat_type)
        observed=quote.observed_at.isoformat()
        group['last_observed_at']=max(group['last_observed_at'] or observed,observed)
        if available:
            confirmed=available.seen_at.isoformat()
            group['last_confirmed_at']=max(group['last_confirmed_at'] or confirmed,confirmed)
        reason=exclusion(game,quote,available,now)
        if reason: group['blockers'][reason]+=1
        else: group['quote_eligible']+=1
    return {'generated_at':now.isoformat(),'window_days':7,'rows_scanned':min(len(rows),20000),
        'truncated':len(rows)>20000,'scope':'Player props only. Latest observation per source/event/player/stat/line within the bounded seven-day sample.',
        'note':'Quote eligibility checks freshness and pregame availability only—not price completeness, history, model qualification, positive EV, or legal availability. No recorded rows does not prove a provider has no coverage.',
        'groups':[{'source':source,'sport':sport,**g,'markets':sorted(g['markets']),'blockers':dict(g['blockers'])}
                  for (source,sport),g in sorted(groups.items())]}
