"""Explicit future-week roster scenarios; never promoted or filled from current week."""
from src.services.fantasy_decision_models import optimize
from src.services.roster_stat_model import finite
from datetime import datetime


def grade_frozen(record, outcomes):
    """Grade the saved lineups, never hindsight-optimize actual player scores.

    Outcomes must be explicitly final, full-scoring and contract/event bound.
    Missing any selected player withholds the entire horizon, not just that week.
    """
    base={'status':'withheld','serving_promoted':False,'actual_gain':None}
    try:
        captured=datetime.fromisoformat(record['captured_at'])
        contract=record['scoring_contract']
        league=record['league_id']
        if not contract or not league or captured.tzinfo is None:raise ValueError()
        forecast=record['forecast']
        if forecast['status']!='conditional_research' or not forecast['weeks']:
            raise ValueError()
    except (KeyError,TypeError,ValueError):
        return {**base,'reason':'invalid_frozen_contract'}
    rows=[]; seen=set()
    for week in forecast['weeks']:
        key=week['week']
        if key in seen:return {**base,'reason':'duplicate_week'}
        seen.add(key)
        totals={}
        for side in ('before','after'):
            lineup=week[side]['lineup']
            ids=[p['player_id'] for p in lineup]
            if not ids or None in ids or len(ids)!=len(set(ids)):
                return {**base,'reason':'invalid_frozen_lineup'}
            total=0
            for pid in ids:
                result=outcomes.get((key,pid),{})
                evidence=record.get('player_games',{}).get(str(key),{}).get(pid,{})
                try:
                    kickoff=datetime.fromisoformat(evidence['kickoff'])
                    observed=datetime.fromisoformat(result['observed_at'])
                    valid=(captured<kickoff<=observed and result.get('status')=='final'
                        and result.get('game_id')==evidence['game_id']
                        and result.get('scoring_contract')==contract
                        and result.get('league_id')==league
                        and finite(result.get('points')))
                except (KeyError,TypeError,ValueError):valid=False
                if not valid:return {**base,'reason':'missing_or_unbound_final_points'}
                total+=result['points']
            totals[side]=total
        rows.append({'week':key,'actual_gain':totals['after']-totals['before']})
    actual=sum(row['actual_gain'] for row in rows)
    predicted=forecast.get('total_gain')
    if not finite(predicted):return {**base,'reason':'invalid_predicted_gain'}
    return {**base,'status':'graded_frozen_scenario','actual_gain':actual,'weeks':rows,
            'predicted_gain':predicted,'absolute_error':abs(actual-predicted),
            'scope':'Saved lineup outcomes, not hindsight-optimal lineups or independent model qualification.'}


def compare(roster, addition, drop_id, slots, weeks):
    base={'status':'withheld','serving_promoted':False,'total_gain':None,'weeks':[]}
    ids=[p['player_id'] for p in roster]
    if (not weeks or len(weeks)!=len(set(weeks)) or len(ids)!=len(set(ids))
        or drop_id not in ids or addition['player_id'] in ids):
        return {**base,'reason':'invalid_scenario'}
    rows=[]
    for week in sorted(weeks):
        pools=[]
        for members in (roster,[p for p in roster if p['player_id']!=drop_id]+[addition]):
            pool=[]
            for p in members:
                evidence=p.get('future_weeks',{}).get(week)
                if not evidence:return {**base,'reason':'missing_future_week_evidence'}
                if evidence.get('status')=='verified_bye':continue
                if (evidence.get('status')!='full_scoring_projection'
                    or not finite(evidence.get('points'))):
                    return {**base,'reason':'incomplete_future_week_projection'}
                pool.append({**p,'weekly_points':evidence['points']})
            pools.append(optimize(pool,slots))
        before,after=pools
        if before['total'] is None or after['total'] is None:
            return {**base,'reason':'unfillable_future_lineup'}
        rows.append({'week':week,'before':before,'after':after,
                     'gain':round(after['total']-before['total'],2)})
    return {**base,'status':'conditional_research','weeks':rows,
            'total_gain':round(sum(r['gain'] for r in rows),2),
            'scope':'Explicit weekly inputs; no injury recovery, future transactions, keeper/dynasty value or prospective qualification inferred.'}
