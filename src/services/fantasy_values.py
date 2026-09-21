"""Transparent redraft research values, distinct from market prices or fairness.

No scraped proprietary projections, dynasty assumptions or fitted injury penalties.
The retained historical candidate supplies production; this layer explains roster fit.
"""
from collections import Counter
from src.services.fantasy_decision_models import optimize, FLEX, RESERVE
from src.services.roster_stat_model import finite

POSITIONS={'QB','RB','WR','TE'}
MODEL='fantasy_roster_value_v1'


def availability_flag(p):
    value=str(p.get('injury_status') or '').strip().upper()
    return value not in ('','ACTIVE','HEALTHY','NORMAL')


def ready(p):
    return (p.get('position') in POSITIONS and
            p.get('ros',{}).get('per_game',{}).get('status')=='candidate' and
            finite(p.get('ros',{}).get('per_game',{}).get('per_game')) and
            finite(p.get('ros',{}).get('full_ros_value')))


def points(p):
    return p['ros']['per_game']['per_game'] if ready(p) else None


def value_board(data):
    if data.get('status')!='candidate': return data
    players=data['players']
    replacements={}
    for pos in sorted(POSITIONS):
        pool=[p for p in players if p.get('position')==pos and not p.get('roster_ids') and ready(p)
              and not availability_flag(p) and p.get('current_season_games',1)>0]
        if pool:
            replacements[pos]=max(pool,key=lambda p:(points(p),p['player_id']))
    rows=[]
    for p in players:
        replacement=replacements.get(p.get('position'))
        blockers=[]
        if not ready(p): blockers.append(p.get('ros',{}).get('per_game',{}).get('status','missing_history'))
        if data['coverage']['stale_inputs']: blockers.append('stale_inputs')
        if availability_flag(p): blockers.append('availability_requires_review')
        if p.get('current_season_games')==0:blockers.append('no_current_season_result_history')
        value=points(p)
        above=round(value-points(replacement),2) if value is not None and replacement else None
        rows.append({**p,'value':{'status':'research_candidate' if not blockers else 'limited',
            'conditional_points_per_game':value,'above_available_replacement_per_game':above,
            'replacement_player':replacement['name'] if replacement else None,
            'market_price':None,'blockers':blockers,'availability_assumption':'conditional_on_playing'}})
    rows.sort(key=lambda p:(points(p) is None,-(points(p) or 0),p['name']))
    return {**data,'players':rows,'valuation_version':MODEL,'market_data_status':'selected_trade_players_only_format_and_freshness_gated',
        'value_coverage':dict(Counter(p['value']['status'] for p in rows)),
        'valuation_notes':[
            'Production values are league-scored research candidates, not market prices or validated trade fairness.',
            'Replacement is the highest modeled unowned same-position player without a reported injury; it may not be claimable.',
            'Unknown player values stay null. Kicker, defense, rookie and incomplete-history coverage can abstain.',
            'Per-game lineup impact assumes everyone plays; it does not model byes, injury recovery, trade processing or dynasty picks.']}


def compare(data, side_a, side_b, *, adjustments=None):
    result={'status':'withheld','model_version':MODEL,'verdict':None,'blockers':[]}
    if (not side_a or not side_b or len(side_a+side_b)>12 or
        len(set(side_a+side_b))!=len(side_a+side_b)):
        return {**result,'blockers':['invalid_or_duplicate_package']}
    players={p['player_id']:p for p in data.get('players',[])}
    if any(pid not in players for pid in side_a+side_b):
        return {**result,'blockers':['unknown_player']}
    if data.get('coverage',{}).get('stale_inputs',True):result['blockers'].append('stale_inputs')
    if any(not ready(players[pid]) for pid in side_a+side_b):result['blockers'].append('incomplete_traded_player_values')
    if any(availability_flag(players[pid]) for pid in side_a+side_b):result['blockers'].append('traded_player_availability_requires_review')
    rosters=data.get('rosters',[])
    def owner(ids):
        matches=[r for r in rosters if set(ids)<=set(r['player_ids'])]
        return matches[0] if len(matches)==1 else None
    a,b=owner(side_a),owner(side_b)
    if not a or not b or a['roster_id']==b['roster_id']:
        return {**result,'blockers':result['blockers']+['packages_must_belong_to_two_distinct_rosters']}
    adjustments=adjustments or {}
    plans={s:{k:list(adjustments.get(s,{}).get(k,[])) for k in ('add','drop')} for s in ('a','b')}
    extra=[pid for plan in plans.values() for ids in plan.values() for pid in ids]
    if len(extra)>12 or len(set(extra))!=len(extra) or set(extra)&set(side_a+side_b):
        return {**result,'blockers':result['blockers']+['invalid_or_duplicate_adjustments']}
    if any(pid not in players for pid in extra):return {**result,'blockers':['unknown_adjustment_player']}
    owned={pid for r in rosters for pid in r['player_ids']}
    for s,roster,give,receive in (('a',a,side_a,side_b),('b',b,side_b,side_a)):
        plan=plans[s]
        if any(pid not in roster['player_ids'] for pid in plan['drop']):result['blockers'].append('drop_not_owned_'+s)
        if any(pid in owned for pid in plan['add']):result['blockers'].append('add_not_free_agent_'+s)
        if len(receive)-len(give)+len(plan['add'])-len(plan['drop'])!=0:
            result['blockers'].append('uneven_trade_requires_explicit_add_drop_plan')
    slots=[s for s in data.get('roster_positions',[]) if s not in RESERVE and s not in ('K','DEF','DST')]
    if not slots or any(not FLEX.get(s,{s})<=POSITIONS for s in slots):
        result['blockers'].append('unsupported_starting_slots')
    def impact(roster,give,receive,plan):
        before_ids=roster['player_ids'];after_ids=[pid for pid in before_ids if pid not in give+plan['drop']]+receive+plan['add']
        def lineup(ids):
            pool=[{**players[pid],'conditional_points':points(players[pid])} for pid in ids if pid in players]
            return optimize(pool,slots,key='conditional_points')
        before,after=lineup(before_ids),lineup(after_ids)
        missing=[pid for pid in set(before_ids+after_ids) if pid not in players or
            (players[pid].get('position') in POSITIONS and not ready(players[pid]))]
        injuries=[pid for pid in set(before_ids+after_ids) if pid in players and
            players[pid].get('position') in POSITIONS and availability_flag(players[pid])]
        complete=not missing and not injuries and before['total'] is not None and after['total'] is not None
        return {'roster_id':roster['roster_id'],'team':roster['name'],'before':before,'after':after,'adjustments':plan,
                'roster_size_before':len(before_ids),'roster_size_after':len(after_ids),
                'missing_player_ids':sorted(missing),'availability_review_ids':sorted(injuries),
                'conditional_lineup_gain':round(after['total']-before['total'],2) if complete else None}
    ia,ib=impact(a,side_a,side_b,plans['a']),impact(b,side_b,side_a,plans['b'])
    if any(i['conditional_lineup_gain'] is None for i in (ia,ib)):result['blockers'].append('incomplete_roster_or_availability')
    return {**result,'status':'research_candidate' if not result['blockers'] else 'withheld',
        'side_a':ia,'side_b':ib,'note':'Side A gives its selected players to B. Gains are conditional offensive lineup points per game, not ROS gains, market fairness, or acceptance advice.'}


def suggestions(data):
    if data.get('coverage',{}).get('stale_inputs',True):return []
    mine=next((r for r in data.get('rosters',[]) if r['is_mine']),None)
    if not mine:return []
    players={p['player_id']:p for p in data['players']}
    def pool(roster):
        return sorted((pid for pid in roster['player_ids'] if pid in players and ready(players[pid])
                       and not availability_flag(players[pid])),key=lambda pid:(-points(players[pid]),pid))[:8]
    matches=[]
    for other in data['rosters']:
        if other['roster_id']==mine['roster_id']:continue
        for give in pool(mine):
            for receive in pool(other):
                r=compare(data,[give],[receive])
                if r['status']=='research_candidate' and min(r['side_a']['conditional_lineup_gain'],r['side_b']['conditional_lineup_gain'])>0:
                    matches.append({'give':players[give]['name'],'receive':players[receive]['name'],
                        'give_id':give,'receive_id':receive,'other_team':other['name'],
                        'your_gain':r['side_a']['conditional_lineup_gain'],'their_gain':r['side_b']['conditional_lineup_gain']})
    return sorted(matches,key=lambda r:(-r['your_gain'],-r['their_gain'],r['give_id'],r['receive_id']))[:12]
