"""Separate immutable observations. No stakes, exposure, actions, or verified CLV."""
import hashlib
import json
from datetime import datetime,timedelta
from pathlib import Path
from uuid import UUID
from sqlalchemy import select
from config.settings import get_settings
from src.models.base import utcnow
from src.models.facts import Game,PlayerPropLine,TeamMarketLine
from src.services.roster_stat_model import finite
from src.services.roster_stat_prospective import publish


def observation(terms,probability,version,now,kickoff,blockers):
    if (not version or not finite(probability) or not 0<=probability<=1 or
        not now<kickoff<=now+timedelta(days=7)):
        return None
    identity={k:v for k,v in terms.items() if k not in ('quote_id','price_american')}
    identity['model_version']=version
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    return {'id':key,'terms':terms,'probability':probability,'model_version':version,
        'captured_at':now.isoformat(),'kickoff':kickoff.isoformat(),'blockers':blockers,
        'cohort':'research_shadow_v1','actionable':False,'stake':None,'exposure':False,
        'scope':'research_price_observation_not_a_wager_or_validated_strategy'}


async def capture(db):
    from src.api.routers.sportsbook import signal_rows,prop_rows
    from src.services.ledger_quotes import resolve_quote
    from src.services.prop_price_comparisons import load
    from src.services.model_version import manifest
    from fastapi import HTTPException
    root=Path(get_settings().raw_archive_dir)/'research-shadow-ledger'
    rows=[('team',r) for r in await signal_rows(db,None)]
    rows += [('player',r) for r in await prop_rows(db,None,live_only=True)]
    rows += [('player',r) for r in (await load(db))['items']]
    written=0; rejected=0; default_version=manifest()['model_version']
    for kind,row in rows:
        # Missing roster confirmation remains in the frozen blockers, not an
        # implied actionability endorsement. Quote/event freshness is mandatory.
        sides=[row['side']] if 'side' in row else ['over','under']
        for side in sides:
            p=row.get('fair_probability') if 'pricing_method' in row else row.get(
                'under_model_probability' if side=='under' else 'model_probability')
            if not finite(p):continue
            try:
                quote=await resolve_quote(db,kind,UUID(row['id']),side)
                if quote['availability']!='current_pregame_offer':continue
                record=observation(quote['terms'],p,row.get('pricing_method') or row.get('model_version') or default_version,
                    utcnow(),datetime.fromisoformat(quote['game_time']),
                    row.get('recommendation_blockers') or row.get('actionability_blockers') or [row.get('exclusion_reason')])
                if record:written+=publish(root/'entries'/f"{record['id']}.json",record)
            except HTTPException as exc:
                if exc.status_code not in (404,409,422):raise
                rejected+=1
    return {'examined':len(rows),'captured':written,'rejected':rejected,'actionable':False}


async def close(db):
    root=Path(get_settings().raw_archive_dir)/'research-shadow-ledger';now=utcnow();written=0
    for path in (root/'entries').glob('*.json'):
        record=json.loads(path.read_text());t=record['terms']
        game=await db.get(Game,UUID(t['game_id']))
        if not game or not game.game_time or game.game_time>now:continue
        if (root/'closes'/f"{record['id']}.json").exists():continue
        cls=PlayerPropLine if t['kind']=='player' else TeamMarketLine
        captured=datetime.fromisoformat(record['captured_at'])
        if captured>=game.game_time:continue
        filters=[cls.game_id==game.id,cls.source==t['book'],cls.line==t['line'],
            cls.observed_at>=captured,cls.observed_at<game.game_time,
            cls.observed_at>=game.game_time-timedelta(minutes=30)]
        if t['kind']=='player':filters += [cls.player_id==UUID(t['player_id']),cls.stat_type==t['market']]
        else:filters += [cls.market==t['market'],cls.side==t['side']]
        quote=await db.scalar(select(cls).where(*filters).order_by(cls.observed_at.desc(),cls.id.desc()).limit(1))
        price=(getattr(quote,t['side']+'_price_american') if t['kind']=='player' else quote.price_american) if quote else None
        if price is None or abs(price)<100:continue
        written+=publish(root/'closes'/f"{record['id']}.json",{'entry_id':record['id'],
            'status':'observed_price_proxy_rules_unverified','actionable':False,'clv_percent':None,
            'quote_id':str(quote.id),'price_american':price,'observed_at':quote.observed_at.isoformat(),
            'kickoff':game.game_time.isoformat(),'captured_at':now.isoformat()})
    return {'captured':written,'actionable':False,'scope':'shadow_only_exact_contract_close_proxies'}
