"""Read-only fantasy candidates; missing data never becomes a zero forecast."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import fmean

from scipy.optimize import linear_sum_assignment
from sqlalchemy import select, or_

from src.models.facts import Game, PlayerGameStat
from src.models.identity import Team
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot, SleeperRoster
from src.services.player_identity import resolve_platform_players
from src.services.result_eligibility import no_pending_correction
from src.services.roster_stat_model import estimate, finite

FLEX = {'FLEX':{'RB','WR','TE'},'SUPER_FLEX':{'QB','RB','WR','TE'},
        'WRRB_FLEX':{'WR','RB'},'REC_FLEX':{'WR','TE'}}
RESERVE = {'BN','IR','TAXI'}
CORE = {'pass_yd':'passing_yards','pass_td':'passing_touchdowns','pass_int':'passing_interceptions',
        'rush_yd':'rushing_yards','rush_td':'rushing_touchdowns','rec_yd':'receiving_yards',
        'rec_td':'receiving_touchdowns','rec':'receptions','fum_lost':'fumbles_lost',
        'pass_2pt':'passing_2pt_conversions','rush_2pt':'rushing_2pt_conversions',
        'rec_2pt':'receiving_2pt_conversions','fum_rec_td':'fumble_recovery_tds',
        'st_td':'special_teams_tds','fum':'fumbles_total','st_ff':'special_teams_ff',
        'st_fum_rec':'special_teams_fum_rec','espn_fg_missed':'fantasy_fg_missed',
        'espn_pat_made':'fantasy_pat_made','espn_fg_40_49':'fantasy_fg_40_49',
        'espn_fg_50_59':'fantasy_fg_50_59','espn_fg_60_plus':'fantasy_fg_60_plus',
        'espn_fg_under_40':'fantasy_fg_under_40','idp_def_tds':'fantasy_def_tds',
        'defensive_conversion_returns':'defensive_conversion_returns','one_point_safeties':'one_point_safeties'}
# These categories apply to team defense or kickers, not offensive players.
NON_OFFENSE = {'int','sack','safe','def_td','fum_rec','ff','blk_kick','xpm','xpmiss','fgmiss'}


def offensive_weights(scoring):
    return {k:float(v) for k,v in scoring.items() if finite(v) and v and
            k not in NON_OFFENSE and not k.startswith(('def_','pts_allow_','fgm','fgmiss','yds_allow_','_'))}


def player_scoring(league,position):
    if league.platform!='espn': return league.scoring_settings,[]
    from src.ingest.espn_fantasy_constants import STAT_ID_TO_KEY,PLAYER_POSITION_MAP
    items=league.raw.get('scoringSettings',{}).get('scoringItems')
    if not items: return league.scoring_settings,['unverified_espn_scoring_rules']
    pos=next((str(k) for k,v in PLAYER_POSITION_MAP.items() if v==position),None)
    weights={}; missing=[]
    effective={item['statId']:item.get('pointsOverrides',{}).get(pos,item.get('points',0)) for item in items}
    extras={63:'fum_rec_td',85:'espn_fg_missed',86:'espn_pat_made',77:'espn_fg_40_49',80:'espn_fg_under_40',
        198:'espn_fg_50_59',201:'espn_fg_60_plus',206:'defensive_conversion_returns',209:'one_point_safeties'}
    grouped=set()
    # Aggregate categories only when every constituent carries the same weight.
    for ids,key in (((93,101,102),'st_td'),((103,104),'idp_def_tds')):
        if all(i in effective for i in ids) and len({effective[i] for i in ids})==1:
            weights[key]=float(effective[ids[0]]); grouped.update(ids)
    for item in items:
        if item['statId'] in grouped: continue
        value=item.get('pointsOverrides',{}).get(pos,item.get('points',0))
        if not value: continue
        key=STAT_ID_TO_KEY.get(item['statId']) or extras.get(item['statId'])
        if key is None: missing.append('espn_stat_'+str(item['statId'])); continue
        if key in weights: missing.append('duplicate_espn_scoring_'+key)
        weights[key]=float(value)
    return weights,missing


def optimize(players, slots, key='weekly_points'):
    """Maximum-weight matching handles overlapping flex slots without greedy bias."""
    slots=[s for s in slots if s not in RESERVE]
    pool={str(p['player_id']):p for p in players}
    pool=[p for p in pool.values() if finite(p.get(key))]
    if not slots:
        return {'status':'no_starting_slots','total':None,'modeled_subtotal':0,'lineup':[]}
    # Dummy assignments represent unknown coverage, not actual zero-point players.
    weights=[[float(p[key]) if p.get('position') in FLEX.get(s,{s}) else -1e9
              for p in pool]+[-1e6]*len(slots) for s in slots]
    rows,cols=linear_sum_assignment(weights,maximize=True)
    picks={int(r):pool[c] if c<len(pool) and weights[r][c]>-1e8 else None for r,c in zip(rows,cols)}
    lineup=[{'slot':s,'player_id':picks[i]['player_id'] if picks[i] else None,
             'name':picks[i]['name'] if picks[i] else None,'points':picks[i][key] if picks[i] else None}
            for i,s in enumerate(slots)]
    complete=all(picks.values())
    subtotal=round(sum(p[key] for p in picks.values() if p),2)
    return {'status':'complete' if complete else 'incomplete','total':subtotal if complete else None,
            'modeled_subtotal':subtotal,'lineup':lineup}


def waiver_moves(mine, free_agents, slots, protected=()):
    before=optimize(mine,slots)
    if before['total'] is None: return {'status':'incomplete_lineup','moves':[],'before':before}
    moves=[]
    # Every suggested move is an explicit roster-size-neutral add/drop.
    for add in free_agents:
        if not finite(add.get('weekly_points')) or add.get('locked'): continue
        best=None
        for drop in mine:
            if drop['player_id'] in protected or drop.get('locked') or not finite(drop.get('weekly_points')): continue
            after=optimize([p for p in mine if p['player_id']!=drop['player_id']]+[add],slots)
            if after['total'] is None: continue
            gain=round(after['total']-before['total'],2)
            if gain>0 and (best is None or gain>best['lineup_gain']):
                best={'add_id':add['player_id'],'add':add['name'],'drop_id':drop['player_id'],
                      'drop':drop['name'],'lineup_gain':gain,'after_total':after['total'],'after_lineup':after['lineup']}
        if best: moves.append(best)
    return {'status':'candidate','before':before,'moves':sorted(moves,key=lambda m:(-m['lineup_gain'],m['add_id']))[:15]}


def historical_candidate(rows, scoring):
    weights=offensive_weights(scoring)
    unsupported=sorted(set(weights)-CORE.keys())
    modeled={k:v for k,v in weights.items() if k in CORE}
    complete=[r for r in rows if all(finite(r['values'].get(CORE[k])) for k in modeled)]
    if not modeled or len(complete)<8:
        # Report core-only estimates separately; never call these full fantasy points.
        usable={k:v for k,v in modeled.items() if sum(finite(r['values'].get(CORE[k])) for r in rows)>=8}
        unsupported=sorted(set(unsupported)|(set(modeled)-set(usable)))
        modeled=usable
        complete=[r for r in rows if all(finite(r['values'].get(CORE[k])) for k in modeled)]
    complete=sorted(complete,key=lambda r:(r['time'],r['game_id']))[-20:]
    if not modeled or len(complete)<8:
        return {'status':'insufficient_history','games':len(complete),'missing_scoring_keys':unsupported,
                'per_game':None,'modeled_subtotal':None}
    totals=[sum(r['values'][CORE[k]]*w for k,w in modeled.items()) for r in complete]
    baseline=fmean(totals)
    candidate=0
    for k,w in modeled.items():
        prediction=estimate(complete,CORE[k])
        workload=prediction['workload_candidate']
        candidate+=w*(workload['mean'] if workload['status']=='ready' else prediction['baseline'])
    return {'status':'partial_scoring' if unsupported else 'candidate','games':len(complete),
            'missing_scoring_keys':unsupported,'per_game':round(candidate,2) if not unsupported else None,
            'modeled_subtotal':round(candidate,2),'baseline_subtotal':round(baseline,2),
            'scoring_weights':{CORE[k]:w for k,w in modeled.items()},'conditional_on_playing':True}


def ros_value(history, games, now, through_week=18, schedule_complete=False):
    remaining=[g for g in games if g.week and g.week<=through_week and g.status=='scheduled' and
               (g.game_time is None or g.game_time>now)]
    # No inferred byes or imaginary games: report the known schedule only.
    value=history.get('modeled_subtotal')
    return {'status':'complete_schedule_candidate' if schedule_complete else 'known_schedule_only','through_week':through_week,'known_remaining_games':len(remaining),
            'unknown_kickoffs':sum(g.game_time is None for g in remaining),
            'known_schedule_subtotal':round(value*len(remaining),2) if value is not None and remaining else None,
            'full_ros_value':round(history['per_game']*len(remaining),2) if schedule_complete and history.get('per_game') is not None else None,'per_game':history,
            'note':'Conditional constant-role candidate; schedule completeness is reported separately. No dynasty or injury-recovery valuation.'}


def trade_comparison(players, side_a, side_b):
    if not side_a or not side_b or len(set(side_a+side_b))!=len(side_a+side_b):
        return {'status':'invalid_package','reason':'Each player must appear exactly once across two nonempty sides.'}
    def side(ids):
        values=[players.get(pid) for pid in ids]
        known=all(p and p.get('ros',{}).get('known_schedule_subtotal') is not None for p in values)
        return {'players':[{'player_id':pid,'name':players.get(pid,{}).get('name',pid),
                            'ros':players.get(pid,{}).get('ros')} for pid in ids],
                'known_schedule_subtotal':round(sum(p['ros']['known_schedule_subtotal'] for p in values),2) if known else None,
                'full_ros_value':round(sum(p['ros']['full_ros_value'] for p in values),2) if values and all(p and p.get('ros',{}).get('full_ros_value') is not None for p in values) else None}
    a,b=side(side_a),side(side_b)
    return {'status':'research_only','side_a':a,'side_b':b,'verdict':None,
            'note':'Partial schedule/scoring values are not trade fairness. No recommendation or automatic acceptance; roster fit and replacement costs remain unpriced.'}


async def build(db, league_id, *, include_catalog=False):
    now=datetime.now(timezone.utc)
    league=await db.get(SleeperLeague,league_id)
    if not league or league.sport!='nfl': return {'status':'unsupported_league','players':[]}
    snapshots=(await db.scalars(select(SleeperLeagueSnapshot).where(SleeperLeagueSnapshot.league_id==league_id)
        .order_by(SleeperLeagueSnapshot.week.desc(),SleeperLeagueSnapshot.synced_at.desc()))).all()
    latest={}
    for row in snapshots: latest.setdefault(row.kind,row)
    meta=latest.get('player_metadata'); proj=latest.get('projections'); matchup=latest.get('matchups'); account=latest.get('account')
    if not all((meta,proj,matchup,account)): return {'status':'missing_snapshots','players':[]}
    catalog=meta.payload if isinstance(meta.payload,dict) else {}
    rosters=(await db.scalars(select(SleeperRoster).where(SleeperRoster.league_id==league_id))).all()
    mine=next((r for r in rosters if r.owner_id==account.payload.get('user_id')),None)
    if mine is None: return {'status':'missing_owner','players':[]}
    owned={str(pid) for r in rosters for pid in r.players}
    raw=proj.payload if isinstance(proj.payload,dict) else {str(r['player_id']):r.get('stats',{}) for r in proj.payload if isinstance(r,dict) and r.get('player_id')}
    def weekly(pid):
        stats=raw.get(pid,{})
        if finite(stats.get('_espn_applied_total')): return float(stats['_espn_applied_total'])
        scoring=league.scoring_settings
        # Ignore ADP-only records. This is a provider component sum, not our historical model.
        if not any(k in scoring and finite(v) and scoring[k] for k,v in stats.items()): return None
        return round(sum(float(stats.get(k,0) or 0)*float(v or 0) for k,v in scoring.items()),2)
    free=sorted((pid for pid in raw if pid not in owned and weekly(pid) is not None),
                key=lambda pid:(-weekly(pid),pid))[:60]
    catalog_ids={str(pid) for pid,info in catalog.items() if isinstance(info,dict) and
        info.get('team') and info.get('active') is not False and
        info.get('position') in ('QB','RB','WR','TE','K','DEF','DST')} if include_catalog else set()
    ids=sorted(owned|set(free)|catalog_ids)
    resolved=await resolve_platform_players(db,league.platform,ids)
    teams=(await db.scalars(select(Team).where(Team.sport=='nfl'))).all()
    alias={'LA':'LAR','WSH':'WAS','JAC':'JAX'}
    team_by_abbr={alias.get(t.nflverse_abbr,t.nflverse_abbr):t.id for t in teams}
    games=(await db.scalars(select(Game).where(Game.sport=='nfl',Game.season==int(league.season),
        or_(Game.game_type.is_(None),Game.game_type=='REG')))).all()
    history=defaultdict(dict)
    facts=(await db.execute(select(PlayerGameStat,Game).join(Game,Game.id==PlayerGameStat.game_id).where(
        PlayerGameStat.player_id.in_([p.id for p in resolved.values()]),Game.sport=='nfl',
        Game.season>=int(league.season)-2,Game.status=='final',Game.game_time.isnot(None),Game.game_time<now,
        or_(Game.game_type.is_(None),Game.game_type=='REG'),no_pending_correction()))).all() if resolved else []
    for fact,g in facts:
        history[fact.player_id].setdefault(g.id,{'game_id':str(g.id),'time':g.game_time,'season':g.season,'values':{}})['values'][fact.stat_type]=fact.value
    stale=any(not 0<=(now-s.synced_at).total_seconds()<=21600 for s in (meta,proj,matchup)) or any(
        not 0<=(now-r.synced_at).total_seconds()<=21600 for r in rosters)
    week=matchup.week
    week_games=[g for g in games if g.week==week]
    weekly_open=bool(week_games) and proj.week==week and not stale and all(
        g.status=='scheduled' and g.game_time and g.game_time>now for g in week_games)
    from src.services.fantasy_schedule import coverage
    schedule_coverage=coverage(games)
    players=[]
    for pid in ids:
        info=catalog.get(pid,{})
        team=team_by_abbr.get(alias.get(info.get('team'),info.get('team')))
        pg=[g for g in games if team and team in (g.home_team_id,g.away_team_id)]
        canonical=resolved.get(pid)
        scoring,rule_gaps=player_scoring(league,info.get('position'))
        h=historical_candidate(list(history[canonical.id].values()),scoring) if canonical and info.get('position') in ('QB','RB','WR','TE') else {'status':'unresolved_or_unsupported','modeled_subtotal':None}
        if rule_gaps and h.get('status') in ('candidate','partial_scoring'):
            h={**h,'status':'partial_scoring','per_game':None,'missing_scoring_keys':h['missing_scoring_keys']+rule_gaps}
        from src.services.fantasy_specialists import candidate as kicking_candidate
        specialist=kicking_candidate(list(history[canonical.id].values()),scoring) if canonical and info.get('position')=='K' else None
        players.append({'specialist_research':specialist,'player_id':pid,'name':' '.join(str(info.get(k) or '') for k in ('first_name','last_name')).strip() or pid,
            'position':info.get('position'),'team':info.get('team'),'weekly_points':weekly(pid),
            'injury_status':info.get('injury_status'),'roster_ids':[r.roster_id for r in rosters if pid in set(map(str,r.players))],
            'history_through':max((r['time'].isoformat() for r in history[canonical.id].values()),default=None) if canonical else None,
            'current_season_games':sum(r['season']==int(league.season) for r in history[canonical.id].values()) if canonical else 0,
            'canonical_player_id':str(canonical.id) if canonical else None,
            'weekly_evidence':{'points':weekly(pid),'week':proj.week,'source':league.platform,
                'scoring_kind':'platform_applied_total' if '_espn_applied_total' in raw.get(pid,{}) else 'provider_component_sum',
                'observed_at':proj.synced_at.isoformat(),
                'status':'pregame_provider_projection' if not stale and proj.week==week and weekly(pid) is not None and
                    len([g for g in pg if g.week==week])==1 and all(g.status=='scheduled' and g.game_time and g.game_time>now for g in pg if g.week==week)
                    else 'unavailable_stale_or_started',
                'scope':'current_week_only_not_ros_or_market_value'},
            'next_games':[{'id':str(g.id),'week':g.week,'kickoff':g.game_time.isoformat() if g.game_time else None,'status':g.status} for g in pg if g.status=='scheduled'],
            'identity_status':'exact' if canonical else 'unresolved','ros':ros_value(h,pg,now,schedule_complete=schedule_coverage['complete'] and team is not None),
            'locked':len([g for g in pg if g.week==week])!=1 or any(g.week==week and (g.game_time is None or g.game_time<=now or g.status!='scheduled') for g in pg)})
    by_id={p['player_id']:p for p in players}
    mine_players=[by_id[str(pid)] for pid in mine.players]
    matchrows=matchup.payload if isinstance(matchup.payload,list) else []
    mymatch=next((r for r in matchrows if r.get('roster_id')==mine.roster_id),{})
    opponent=next((r for r in matchrows if mymatch.get('matchup_id') is not None and r.get('matchup_id')==mymatch['matchup_id'] and r.get('roster_id')!=mine.roster_id),None)
    def total(ids):
        vals=[by_id.get(str(pid),{}).get('weekly_points') for pid in ids]
        return round(sum(vals),2) if vals and all(finite(v) for v in vals) else None
    a=total(mymatch.get('starters',[])); b=total(opponent.get('starters',[])) if opponent else None
    # Unknown team/game binding is not an inferred bye or an unlocked player.
    matchup_bound=bool(opponent) and all(not by_id.get(str(pid),{}).get('locked',True)
        for pid in mymatch.get('starters',[])+(opponent.get('starters',[]) if opponent else []))
    return {'status':'candidate','league_id':league_id,'league_name':league.name,'week':week,'generated_at':now.isoformat(),
        'roster_positions':league.roster_positions,
        'rosters':[{'roster_id':r.roster_id,'name':r.team_name or str(r.roster_id),'is_mine':r is mine,
                    'player_ids':list(map(str,r.players))} for r in rosters],
        'input_timestamps':{kind:row.synced_at.isoformat() for kind,row in latest.items() if kind in ('player_metadata','projections','matchups')},
        'model_version':'fantasy_decisions_v2','serving_replaced':False,'scoring_settings':league.scoring_settings,
        'coverage':{'stale_inputs':stale,'projection_week':proj.week,'weekly_decisions_open':weekly_open,
                    'schedule':schedule_coverage,'scheduled_rows':len(games),'player_pool':len(players),'free_agent_candidates':len(free),
                    'history_statuses':dict(Counter(p['ros']['per_game']['status'] for p in players))},
        'matchup':{'status':'pregame_candidate' if weekly_open and matchup_bound and a is not None and b is not None else 'withheld',
                   'your_pregame_projection':a,'opponent_pregame_projection':b,
                   'projected_margin':round(a-b,2) if weekly_open and matchup_bound and a is not None and b is not None else None,
                   'win_probability':None,'reason':'Pregame only; no calibrated win probability or remaining-points model. Started games, stale inputs and missing projections block decisions.'},
        'waivers':waiver_moves(mine_players,[by_id[p] for p in free],league.roster_positions,set(map(str,mine.starters))) if weekly_open else {'status':'withheld_stale_or_started_week','moves':[]},
        'validation_lineups':{'your_starters':mymatch.get('starters',[]),'opponent_starters':opponent.get('starters',[]) if opponent else [],
            'games':[{'id':str(g.id),'kickoff':g.game_time.isoformat() if g.game_time else None} for g in week_games]},
        'players':players,'notes':['Read-only candidates; no lineup, waiver claim or trade is submitted.',
          'Weekly projections use provider-supplied scoring components, not ADP; missing projection rows remain unknown.',
          'Full ROS requires complete schedule membership and scoring history; otherwise only a labeled subtotal is shown.',
          'ROS assumes constant role and participation. Prospective validation is required; no injury-recovery, opponent or dynasty adjustments.']}
