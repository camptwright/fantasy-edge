"""Sharp-to-soft player quotes; exact identity/line only, never actionable."""
from collections import defaultdict
from datetime import timedelta
import math
from sqlalchemy import select
from src.models.facts import Game, PlayerPropLine
from src.services.quote_eligibility import availability, exclusion
from src.services.sharp_pricing import SHARP, TARGETS, brand
from src.utils.odds_math import remove_vig_two_way, expected_value_percent


def valid_price(value):
    return isinstance(value,int) and not isinstance(value,bool) and abs(value)>=100


def compare(rows):
    references=defaultdict(dict); targets=[]
    for q,g in rows:
        book=brand(q.source)
        if (not q.game_id or not q.player_id or not isinstance(q.line,(int,float)) or
            isinstance(q.line,bool) or not math.isfinite(q.line) or float(q.line).is_integer()):
            continue
        key=(q.game_id,q.player_id,q.stat_type,q.line)
        if book in SHARP:
            if not all(valid_price(v) for v in (q.over_price_american,q.under_price_american)):continue
            old=references[key].get(book)
            if old is None or (q.observed_at,str(q.id))>(old[0].observed_at,str(old[0].id)):
                references[key][book]=(q,remove_vig_two_way(q.over_price_american,q.under_price_american))
        elif book in TARGETS:
            targets.append((key,q,g))
    output=[]
    for key,q,g in targets:
        refs={b:r for b,r in references[key].items() if abs(r[0].observed_at-q.observed_at)<=timedelta(minutes=5)}
        if not refs:continue
        for index,side in enumerate(('over','under')):
            price=getattr(q,side+'_price_american')
            if not valid_price(price):continue
            probability=sum(r[1][index] for r in refs.values())/len(refs)
            output.append({'id':str(q.id),'game_id':str(g.id),'player_id':str(q.player_id),
                'sport':g.sport,'kind':'player','market':q.stat_type,'stat_type':q.stat_type,
                'side':side,'line':q.line,'source':q.source,'bookmaker':brand(q.source),
                'price_american':price,'fair_probability':probability,
                'ev_percent':expected_value_percent(probability,price),
                'reference_books':sorted(refs),'reference_quote_ids':[str(refs[b][0].id) for b in sorted(refs)],
                'observed_at':q.observed_at.isoformat(),
                'pricing_method':'sharp_exact_player_contract_v1','actionable':False,'usage':'research_only',
                'exclusion_reason':'unvalidated_strategy_and_settlement_rules'})
    return sorted(output,key=lambda r:(-r['ev_percent'],r['id'],r['side']))


async def load(db,sport=None):
    q=PlayerPropLine
    keys=(q.game_id,q.player_id,q.stat_type,q.source)
    stmt=select(q,Game).join(Game,Game.id==q.game_id).where(Game.status=='scheduled')
    if sport:stmt=stmt.where(Game.sport==sport)
    rows=(await db.execute(stmt.distinct(*keys).order_by(*keys,q.observed_at.desc(),q.id.desc()))).all()
    seen=await availability(db,'prop',[q.id for q,g in rows])
    fresh=[(q,g) for q,g in rows if exclusion(g,q,seen.get(q.id)) is None]
    return {'items':compare(fresh),'fresh_quotes':len(fresh)}
