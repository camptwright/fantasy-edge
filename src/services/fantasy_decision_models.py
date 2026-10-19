"""Read-only fantasy candidates; missing data never becomes a zero forecast."""
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from statistics import fmean

from scipy.optimize import linear_sum_assignment
from sqlalchemy import select, or_

from src.models.facts import Game, PlayerGameStat
from src.models.identity import Team
from src.models.sleeper import FantasyNeverDrop, SleeperLeague, SleeperLeagueSnapshot, SleeperRoster
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
        return {'status':'insufficient_history','games':len(complete) if modeled else 0,'missing_scoring_keys':unsupported,
                'available_games':len(rows),
                'missing_category_counts':{k:sum(not finite(r['values'].get(CORE[k])) for r in rows) for k in weights if k in CORE},
                'per_game':None,'modeled_subtotal':None}
    totals=[sum(r['values'][CORE[k]]*w for k,w in modeled.items()) for r in complete]
    baseline=fmean(totals)
    candidate=0
    for k,w in modeled.items():
        prediction=estimate(complete,CORE[k])
        workload=prediction['workload_candidate']
        candidate+=w*(workload['mean'] if workload['status']=='ready' else prediction['baseline'])
    return {'status':'partial_scoring' if unsupported else 'candidate','games':len(complete),
            'score_samples':totals if not unsupported else [],
            'available_games':len(rows),
            'missing_category_counts':{k:sum(not finite(r['values'].get(CORE[k])) for r in rows) for k in weights if k in CORE},
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


def input_deadline(meta, proj, matchup, rosters, platform, now):
    """Daily bulk catalog cadence is distinct from live roster/projection freshness."""
    sources=[(meta,26 if platform=='sleeper' else 6),
             *[(row,6) for row in (proj,matchup,*rosters)]]
    if any(row.synced_at>now for row,_ in sources):return None
    return min(row.synced_at+timedelta(hours=hours) for row,hours in sources)


ENGINE_MAX_AGE=timedelta(hours=3)


def engine_research(players,resolved,checkpoint,league,week,now,key='engine'):
    """Attach engine projections under `key`: v1 (projection_engine_serving) or v2 (projection_engine_v2_serving).

    Weekly points for the selected week, the next weeks and a remaining-season
    sum over games not yet started. Conditional on playing. v1 is research
    only; v2's week points enter decisions through blend_engine_v2.
    """
    from src.services.engine_research import player_points
    fresh=(checkpoint is not None and checkpoint.get('status')=='research' and
           timedelta(0)<=now-datetime.fromisoformat(checkpoint['generated_at'])<=ENGINE_MAX_AGE)
    for p in players:
        canonical=resolved.get(p['player_id'])
        if p.get('position') not in ('QB','RB','WR','TE'):
            p[key]={'status':'position_not_modeled'};continue
        if not fresh:
            p[key]={'status':'missing_or_stale_engine_research'};continue
        weeks=checkpoint['players'].get(str(canonical.id)) if canonical else None
        if not weeks:
            p[key]={'status':'not_projected' if canonical else 'unresolved_identity',
                    'generated_at':checkpoint['generated_at']};continue
        scoring,gaps=player_scoring(league,p['position'])
        weights={CORE[k]:w for k,w in offensive_weights(scoring).items() if k in CORE}
        upcoming={g['id'] for g in p.get('next_games',[]) if g.get('kickoff') and datetime.fromisoformat(g['kickoff'])>now}
        rows=[]
        for w,entry in sorted(weeks.items(),key=lambda kv:int(kv[0])):
            if int(w)<week or entry['game_id'] not in upcoming:continue
            meta=checkpoint['games'].get(entry['game_id'],{})
            rows.append({'week':int(w),'points':player_points(entry,weights),
                         'environment':meta.get('environment','unknown')})
        p[key]={'status':'research_partial_scoring' if gaps else 'research',
            'generated_at':checkpoint['generated_at'],'version':checkpoint.get('engine_version'),
            'week_points':next((r['points'] for r in rows if r['week']==week),None),
            'weeks':rows,'ros_points':round(sum(r['points'] for r in rows),2) if rows else None,
            'ros_games':len(rows),'ros_lined_games':sum(r['environment']=='market_line' for r in rows),
            'conditional_on_playing':True,'serving_promoted':False}


V2_WEIGHT=0.5


def blend_engine_v2(players):
    """Owner decision 2026-10-15: projections are 50/50 provider + engine v2 points.

    The fixed half-weight blend was the best measured on frozen 2026 Weeks 2-5
    (docs/2026-10-15-engine-v2-plan.md), though v2 failed its registered 2022
    test. Blends only when the provider projects a positive total (a zero is
    usually out or a bye; v2 is conditional on playing) and v2 scores every
    category of the player's rules. K, DEF and unprojected players keep the
    provider value. `provider_points` keeps the provider's own number.
    """
    for p in players:
        provider,engine=p['weekly_points'],p.get('engine_v2') or {}
        p['provider_points']=provider
        p['projection_source']='provider'
        if finite(provider) and provider>0 and engine.get('status')=='research' and finite(engine.get('week_points')):
            p['weekly_points']=round((1-V2_WEIGHT)*provider+V2_WEIGHT*engine['week_points'],2)
            p['projection_source']='blend_provider_engine_v2'


async def build(db, league_id, *, include_catalog=False, catalog_offset=0, catalog_limit=50,
                selected_player_ids=()):
    if catalog_offset < 0 or not 1 <= catalog_limit <= 100:
        raise ValueError('Catalog requires a nonnegative offset and limit from 1 to 100')
    now=datetime.now(timezone.utc)
    league=await db.get(SleeperLeague,league_id)
    if not league or league.sport!='nfl': return {'status':'unsupported_league','players':[]}
    snapshots=(await db.scalars(select(SleeperLeagueSnapshot).where(SleeperLeagueSnapshot.league_id==league_id)
        .order_by(SleeperLeagueSnapshot.week.desc(),SleeperLeagueSnapshot.synced_at.desc()))).all()
    latest={}
    for row in snapshots: latest.setdefault(row.kind,row)
    # A newer projection alone must not be paired with last week's opponent.
    common=sorted({s.week for s in snapshots if s.kind=='projections'} &
                  {s.week for s in snapshots if s.kind=='matchups'},reverse=True)
    games=(await db.scalars(select(Game).where(Game.sport=='nfl',Game.season==int(league.season),
        or_(Game.game_type.is_(None),Game.game_type=='REG')))).all()
    upcoming=sorted({g.week for g in games if g.week and g.status=='scheduled' and g.game_time and g.game_time>now})
    selected_week=upcoming[0] if upcoming and upcoming[0] in common else next(
        (w for w in common if not upcoming or w<=upcoming[0]),None)
    if selected_week is not None:
        for kind in ('projections','matchups'):
            latest[kind]=next(s for s in snapshots if s.kind==kind and s.week==selected_week)
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
    catalog_page=sorted(catalog_ids-owned-set(free))[catalog_offset:catalog_offset+catalog_limit]
    # Always retain the league rosters and replacement pool. Only the additional
    # catalog is paged; selected trade participants are explicitly included.
    ids=sorted(owned|set(free)|set(catalog_page)|set(map(str,selected_player_ids)))
    resolved=await resolve_platform_players(db,league.platform,ids)
    teams=(await db.scalars(select(Team).where(Team.sport=='nfl'))).all()
    alias={'LA':'LAR','WSH':'WAS','JAC':'JAX'}
    team_by_abbr={alias.get(t.nflverse_abbr,t.nflverse_abbr):t.id for t in teams}
    team_names={t.id:t.name for t in teams}
    history=defaultdict(dict)
    facts=(await db.stream(select(PlayerGameStat.player_id,PlayerGameStat.game_id,
        PlayerGameStat.stat_type,PlayerGameStat.value,Game.game_time,Game.season)
        .join(Game,Game.id==PlayerGameStat.game_id).where(
        PlayerGameStat.player_id.in_([p.id for p in resolved.values()]),Game.sport=='nfl',
        Game.season>=int(league.season)-2,Game.status=='final',Game.game_time.isnot(None),Game.game_time<now,
        or_(Game.game_type.is_(None),Game.game_type=='REG'),no_pending_correction())
        .execution_options(yield_per=1000))) if resolved else None
    if facts is not None:
        async for fact in facts:
            history[fact.player_id].setdefault(fact.game_id,{'game_id':str(fact.game_id),
                'time':fact.game_time,'season':fact.season,'values':{}})['values'][fact.stat_type]=fact.value
    deadline=input_deadline(meta,proj,matchup,rosters,league.platform,now)
    stale=deadline is None or now>=deadline
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
        weekly_games=[g for g in pg if g.week==week]
        opponent_id=(weekly_games[0].away_team_id if weekly_games[0].home_team_id==team else weekly_games[0].home_team_id) if len(weekly_games)==1 else None
        canonical=resolved.get(pid)
        scoring,rule_gaps=player_scoring(league,info.get('position'))
        h=historical_candidate(list(history[canonical.id].values()),scoring) if canonical and info.get('position') in ('QB','RB','WR','TE') else {'status':'unresolved_or_unsupported','modeled_subtotal':None}
        if rule_gaps and h.get('status') in ('candidate','partial_scoring'):
            h={**h,'status':'partial_scoring','per_game':None,'missing_scoring_keys':h['missing_scoring_keys']+rule_gaps}
        from src.services.fantasy_specialists import candidate as kicking_candidate
        specialist=kicking_candidate(list(history[canonical.id].values()),scoring) if canonical and info.get('position')=='K' else None
        players.append({'specialist_research':specialist,'player_id':pid,'name':' '.join(str(info.get(k) or '') for k in ('first_name','last_name')).strip() or pid,
            'replacement_pool_member':pid in free,
            'opponent':team_names.get(opponent_id),'news_status':'not_wired_to_fantasy_view',
            'position':info.get('position'),'team':info.get('team'),'weekly_points':weekly(pid),
            'injury_status':info.get('injury_status'),'roster_ids':[r.roster_id for r in rosters if pid in set(map(str,r.players))],
            'availability_observed_at':meta.synced_at.isoformat(),
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
            'nfl_team_id':str(team) if team else None,'nfl_opponent_id':str(opponent_id) if opponent_id else None,
            'week_game_status':('no_game_this_week' if team and not weekly_games else weekly_games[0].status if len(weekly_games)==1 else None),
            'week_kickoff':weekly_games[0].game_time.isoformat() if len(weekly_games)==1 and weekly_games[0].game_time else None,
            'locked':len([g for g in pg if g.week==week])!=1 or any(g.week==week and (g.game_time is None or g.game_time<=now or g.status!='scheduled') for g in pg)})
    # Event evidence is collected elsewhere; only bind its archived observations
    # during background model construction, never during a preview GET.
    from src.services.lab_availability import contexts as availability_contexts
    bound_games={}
    for p in players:
        canonical=resolved.get(p['player_id'])
        candidates=[g for g in week_games if str(g.id) in {r['id'] for r in p['next_games']}]
        if canonical:
            bound_games[canonical.id]=candidates[0] if len(candidates)==1 else None
    availability=await availability_contexts(db,'nfl',list(bound_games),bound_games,now)
    for p in players:
        canonical=resolved.get(p['player_id'])
        p['game_availability']=availability.get(canonical.id,{}) if canonical else {
            'status':'team_unit_not_individual' if p['position'] in ('DEF','DST') else 'missing_provider_identity',
            'hold_recommendation':False,'official_game_status_verified':False}
    from src.services.engine_research import latest as engine_latest
    engine_research(players,resolved,await engine_latest(db),league,week,now)
    from src.services.engine_research import V2_NAME
    v2_checkpoint=await engine_latest(db,V2_NAME)
    engine_research(players,resolved,v2_checkpoint,league,week,now,key='engine_v2')
    blend_engine_v2(players)
    from src.services.engine_coverage import attach_coverage
    attach_coverage(players,games,schedule_coverage,week,now)
    by_id={p['player_id']:p for p in players}
    from src.services.fantasy_score_history import distributions,scoring_hash
    official_rules=league.raw.get('scoringSettings') if league.platform=='espn' else None
    platform_history=distributions(snapshots,league.scoring_settings,league.season,week,now,official_rules)
    specialist_history={}
    if league.platform=='sleeper':
        from src.services.fantasy_component_history import ARCHIVE_ID,distributions as component_distributions
        archives=(await db.scalars(select(SleeperLeagueSnapshot).where(SleeperLeagueSnapshot.league_id==ARCHIVE_ID))).all()
        specialist_history=component_distributions(archives,snapshots,league.scoring_settings,league.season,week,now)
    for p in players:
        h=p['ros']['per_game']
        p['score_samples']=h.get('score_samples',[])
        p['distribution_evidence']=platform_history.get(p['player_id'],
            {'status':'missing_platform_history','games':0,'score_samples':[]})
        p['distribution_source']='complete_component_history' if p['score_samples'] else None
        if not p['score_samples'] and p['distribution_evidence']['score_samples']:
            p['score_samples']=p['distribution_evidence']['score_samples']
            p['distribution_source']='league_scored_provider_history'
        if not p['score_samples'] and p['player_id'] in specialist_history:
            p['distribution_evidence']=specialist_history[p['player_id']]
            p['score_samples']=p['distribution_evidence']['score_samples']
            if p['score_samples']:p['distribution_source']='reconciled_sleeper_component_history'
        if not p['score_samples'] and p['position'] in ('K','DEF'):
            p['distribution_evidence']={**p['distribution_evidence'],
                'status':'assumed_position_prior','recipe':'explicit_specialist_default_v1',
                'standard_deviation':5.0 if p['position']=='K' else 7.0,
                'label':'Explicit unvalidated default, not measured player variance',
                'uses_synthetic_history':False}
            p['distribution_source']='assumed_specialist_default'
        p['is_mine']=p['player_id'] in set(map(str,mine.players))
        p['decision_tier']='estimated' if p['weekly_evidence']['status']=='pregame_provider_projection' else 'ranked_only'
        p['decision_points']=p['weekly_points'] if p['decision_tier']=='estimated' else None
        p['decision_source']=('fresh_blend_provider_engine_v2' if p['projection_source']=='blend_provider_engine_v2'
            else 'fresh_provider_projection') if p['decision_points'] is not None else 'unpriced_roster_context'
        # A missing provider row can fall back to recent complete same-rule
        # history, but stale feeds, unknown games and partial scoring cannot.
        if (p['decision_points'] is None and not stale and proj.week==week and not p['locked']
            and h.get('status')=='candidate' and finite(h.get('per_game')) and p['history_through']
            and 0<=(now-datetime.fromisoformat(p['history_through'])).total_seconds()<=28*86400):
            p['decision_points']=h['per_game']
            p['decision_tier']='estimated_history'
            p['decision_source']='recent_complete_history_conditional_on_playing'
        p['history_diagnostics']={'eligible_games':len(history[resolved[p['player_id']].id]) if p['player_id'] in resolved else 0,
            'complete_scored_games':h.get('games',0),'missing_scoring_keys':h.get('missing_scoring_keys',[]),
            'missing_category_counts':h.get('missing_category_counts',{}),
            'identity_status':p['identity_status'], 'position_supported':p['position'] in ('QB','RB','WR','TE')}
    from src.services.fantasy_specialist_totals import ros_research
    specialist_ros=ros_research(players,snapshots,league,catalog,week,now)
    for p in players:p['specialist_ros_research']=specialist_ros.get(p['player_id'])
    protected={str(pid) for pid in (getattr(mine,'reserve',None) or [])+(getattr(mine,'taxi',None) or [])}
    never_drop=set((await db.scalars(select(FantasyNeverDrop.player_id).where(FantasyNeverDrop.league_id==league_id))).all())
    for p in players:p['never_drop']=p['player_id'] in never_drop
    mine_players=[by_id[str(pid)] for pid in mine.players]
    planning_roster=[str(pid) for pid in mine.players if str(pid) not in protected]
    from src.services.waiver_guidance import guidance as waiver_guidance
    waiver_plans={str(h):waiver_guidance(players,planning_roster,owned,league.roster_positions,
        start_week=week,horizon_weeks=h,keep=never_drop) for h in (2,3,4)}
    matchrows=matchup.payload if isinstance(matchup.payload,list) else []
    mymatch=next((r for r in matchrows if r.get('roster_id')==mine.roster_id),{})
    opponent=next((r for r in matchrows if mymatch.get('matchup_id') is not None and r.get('matchup_id')==mymatch['matchup_id'] and r.get('roster_id')!=mine.roster_id),None)
    def total(ids):
        vals=[by_id.get(str(pid),{}).get('decision_points') for pid in ids]
        return round(sum(vals),2) if vals and all(finite(v) for v in vals) else None
    a=total(mymatch.get('starters',[])); b=total(opponent.get('starters',[])) if opponent else None
    # Unknown team/game binding is not an inferred bye or an unlocked player.
    matchup_bound=bool(opponent) and all(not by_id.get(str(pid),{}).get('locked',True)
        for pid in mymatch.get('starters',[])+(opponent.get('starters',[]) if opponent else []))
    planning_weeks=sorted({g.week for g in games if g.week and g.status=='scheduled' and g.game_time and g.game_time>now})
    from src.services.fantasy_simulation import evaluate
    simulation=evaluate(players,list(map(str,mymatch.get('starters',[]))),
        list(map(str,opponent.get('starters',[]))) if opponent else [],league.roster_positions)
    from src.services.fantasy_outcomes import research as outcome_research
    from src.services.waiver_guidance import guidance as waiver_guidance
    recorded={str(k):v for r in matchrows if r.get('roster_id') in (mine.roster_id,(opponent or {}).get('roster_id'))
              for k,v in (r.get('players_points') or {}).items()}
    outcomes=outcome_research(by_id,list(map(str,mymatch.get('starters',[]))),
        list(map(str,opponent.get('starters',[]))) if opponent else [],
        list(map(str,mine.players)),league.roster_positions,recorded,now) if matchup.week==week else {
        'status':'withheld','reason':'matchup_week_mismatch'}
    from src.services.fantasy_locks import lineup as locked_lineup, waivers as locked_waivers
    starters=list(map(str,mymatch.get('starters',[])))
    decisions_fresh=not stale and proj.week==week
    lineup_decision=locked_lineup(mine_players,league.roster_positions,starters) if decisions_fresh else {
        'status':'stale_inputs','lineup':[],'total':None,'unlocked_points':None}
    from src.services.fantasy_prospective import version as prospective_version
    return {'status':'candidate','league_id':league_id,'league_name':league.name,'season':int(league.season),'week':week,'generated_at':now.isoformat(),
        'input_valid_until':None if stale else deadline.isoformat(),
        'catalog_page':{'offset':catalog_offset,'limit':catalog_limit,
            'total_additional_players':len(catalog_ids-owned-set(free)),
            'next_offset':catalog_offset+catalog_limit if catalog_offset+catalog_limit<len(catalog_ids-owned-set(free)) else None,
            'scope':'All league rosters and top replacement candidates, plus a bounded catalog page'},
        'roster_positions':league.roster_positions,
        'planning_week':planning_weeks[0] if planning_weeks else None,
        'planning_status':'aligned' if planning_weeks and planning_weeks[0]==week else 'awaiting_matching_week_snapshots',
        'lineup_simulation':simulation,
        'outcome_simulation':outcomes,
        'lineup_decision':lineup_decision,
        'matchup_rosters':{'mine':mymatch,'opponent':opponent},
        'fallback_rankings':[{ 'player_id':p['player_id'],'name':p['name'],'tier':p['decision_tier'],
            'points':p['decision_points'],'locked':p['locked']} for p in sorted(players,
                key=lambda p:(p['decision_points'] is None,-(p['decision_points'] or 0),p['name']))],
        'rosters':[{'roster_id':r.roster_id,'name':r.team_name or str(r.roster_id),'is_mine':r is mine,
                    'player_ids':list(map(str,r.players)),
                    'waiver_position':(r.settings or {}).get('waiver_position')} for r in rosters],
        'waiver_guidance':waiver_plans['2'], 'waiver_guidance_by_horizon':waiver_plans,
        'waiver_settings':{'platform':league.platform,'waiver_type':(league.settings or {}).get('waiver_type'),
                           'waiver_clear_days':(league.settings or {}).get('waiver_clear_days')},
        'input_timestamps':{kind:row.synced_at.isoformat() for kind,row in latest.items() if kind in ('player_metadata','projections','matchups')},
        'model_version':'fantasy_decisions_v5','recipe_version':prospective_version(),
        'serving_replaced':False,'scoring_settings':league.scoring_settings,
        'never_drop':sorted(never_drop),
        'projection_blend':{'engine_v2_weight':V2_WEIGHT,'engine_v2_version':(v2_checkpoint or {}).get('engine_version'),
            'engine_v2_generated_at':(v2_checkpoint or {}).get('generated_at'),
            'blended_players':sum(p['projection_source']=='blend_provider_engine_v2' for p in players)},
        'scoring_contract_hash':scoring_hash(league.scoring_settings,official_rules),
        'coverage':{'stale_inputs':stale,'projection_week':proj.week,'weekly_decisions_open':weekly_open,
                    'schedule':schedule_coverage,'scheduled_rows':len(games),'player_pool':len(players),'free_agent_candidates':len(free),
                    'history_statuses':dict(Counter(p['ros']['per_game']['status'] for p in players))},
        'matchup':{'status':'pregame_candidate' if not stale and proj.week==week and matchup_bound and a is not None and b is not None else 'withheld',
                   'your_pregame_projection':a,'opponent_pregame_projection':b,
                   'projected_margin':round(a-b,2) if not stale and proj.week==week and matchup_bound and a is not None and b is not None else None,
                   'win_probability':None,'reason':'Pregame only; no calibrated win probability or remaining-points model. Started games, stale inputs and missing projections block decisions.'},
        'waivers':locked_waivers(mine_players,[by_id[p] for p in free],league.roster_positions,starters,
            keep=protected|never_drop) if decisions_fresh else {'status':'withheld_stale_inputs','moves':[]},
        'validation_lineups':{'your_starters':mymatch.get('starters',[]),'opponent_starters':opponent.get('starters',[]) if opponent else [],
            'games':[{'id':str(g.id),'kickoff':g.game_time.isoformat() if g.game_time else None} for g in week_games]},
        'players':players,'notes':['Read-only candidates; no lineup, waiver claim or trade is submitted.',
          'Weekly projections use provider-supplied scoring components, not ADP; missing projection rows remain unknown.',
          'QB/RB/WR/TE weekly projections are 50/50 provider + engine v2 where v2 projects the player; provider_points keeps the provider value.',
          'Full ROS requires complete schedule membership and scoring history; otherwise only a labeled subtotal is shown.',
          'ROS assumes constant role and participation. Prospective validation is required; no injury-recovery, opponent or dynasty adjustments.']}
