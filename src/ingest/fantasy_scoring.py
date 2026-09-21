"""Supplemental fantasy scoring from explicit nflverse weekly observations.

Only exact GSIS identities and verified final games qualify. Existing facts
use the same two-observation correction ledger as live boxscore results.
"""
import csv
import hashlib
import io
import gzip
from collections import defaultdict, Counter
from datetime import datetime, timezone
import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from src.models.facts import Game, PlayerGameStat
from src.models.identity import Player, Team
from src.models.governance import ResultCorrection
from src.ingest.result_repair import observe

FIELDS={'fumbles_lost':'fumbles_lost_total','passing_2pt_conversions':'passing_2pt_conversions',
    'rushing_2pt_conversions':'rushing_2pt_conversions','receiving_2pt_conversions':'receiving_2pt_conversions',
    'fumble_recovery_tds':'fumble_recovery_tds','special_teams_tds':'special_teams_tds',
    'fumbles_total':'fumbles_total',
    'passing_yards':'passing_yards','passing_touchdowns':'passing_tds','passing_interceptions':'passing_interceptions',
    'passing_attempts':'attempts','passing_completions':'completions','rushing_yards':'rushing_yards',
    'rushing_touchdowns':'rushing_tds','rushing_attempts':'carries','receiving_yards':'receiving_yards',
    'receiving_touchdowns':'receiving_tds','receptions':'receptions','targets':'targets',
    'fantasy_fg_missed':'fg_missed','fantasy_pat_made':'pat_made','fantasy_pat_missed':'pat_missed',
    'fantasy_fg_0_19':'fg_made_0_19','fantasy_fg_20_29':'fg_made_20_29','fantasy_fg_30_39':'fg_made_30_39',
    'fantasy_fg_40_49':'fg_made_40_49','fantasy_fg_50_59':'fg_made_50_59',
    'fantasy_fg_60_plus':'fg_made_60_','fantasy_def_tds':'def_tds'}


def special_teams(rows):
    """Count only attributed kick/punt fumbles; park ambiguous game sequences."""
    totals=defaultdict(lambda:defaultdict(lambda: {'special_teams_ff':0,'special_teams_fum_rec':0,
        'defensive_conversion_returns':0,'one_point_safeties':0}))
    last={}; seen=set(); invalid=set()
    for row in rows:
        gid=row['game_id']; key=(gid,row['play_id'])
        if key in seen: invalid.add(gid)
        seen.add(key); last[gid]=row
        if row.get('play_type')=='no_play': continue
        if not {'defensive_two_point_conv','defensive_extra_point_conv','safety','two_point_attempt','extra_point_attempt'}.issubset(row):
            invalid.add(gid)
        if row.get('defensive_two_point_conv')=='1' or row.get('defensive_extra_point_conv')=='1':
            pid=row.get('td_player_id')
            if not pid: invalid.add(gid)
            else: totals[gid][pid]['defensive_conversion_returns']+=1
        # A rare try safety needs separate role adjudication. Do not assign it
        # to an arbitrary participant or publish zeros for that game's players.
        if row.get('safety')=='1' and (row.get('two_point_attempt')=='1' or row.get('extra_point_attempt')=='1'):
            invalid.add(gid)
        if row.get('kickoff_attempt')!='1' and row.get('punt_attempt')!='1': continue
        if row.get('fumble')!='1': continue
        forced={row.get(f'forced_fumble_player_{i}_player_id') for i in (1,2)}-{None,''}
        if row.get('fumble_forced')=='1' and not forced: invalid.add(gid)
        for pid in forced: totals[gid][pid]['special_teams_ff']+=1
        fumbled={row.get(f'fumbled_{i}_team') for i in (1,2)}-{None,''}
        if len(fumbled)!=1: invalid.add(gid); continue
        for i in (1,2):
            pid=row.get(f'fumble_recovery_{i}_player_id'); team=row.get(f'fumble_recovery_{i}_team')
            if team and team not in fumbled:
                if not pid: invalid.add(gid)
                else: totals[gid][pid]['special_teams_fum_rec']+=1
    valid={gid:(int(float(r['total_home_score'])),int(float(r['total_away_score'])))
        for gid,r in last.items() if gid not in invalid and r.get('desc','').strip()=='END GAME'}
    return totals,valid


def parse(row):
    values={}
    for stat,field in FIELDS.items():
        raw=row.get(field)
        if raw in (None,'','NA'): continue
        n=float(raw)
        if not n.is_integer() or (n<0 and 'yards' not in stat): raise ValueError('invalid outcome')
        values[stat]=n
    buckets=[row.get(k) for k in ('fg_made_0_19','fg_made_20_29','fg_made_30_39')]
    if all(x not in (None,'','NA') for x in buckets):
        nums=[float(x) for x in buckets]
        if any(not n.is_integer() or n<0 for n in nums): raise ValueError('invalid FG count')
        values['fantasy_fg_under_40']=sum(nums)
    return values


def preserve_confirmed_boxscore(fact, confirmed):
    """A supplemental source cannot reverse an already-confirmed ESPN value.

    This is explicit source precedence, not a claim that disagreement is resolved.
    Only the exact current value backed by the latest applied ESPN correction is
    protected. Missing stats still backfill and supplemental-only stats still correct.
    """
    return fact.id in confirmed and confirmed[fact.id] == fact.value


async def sync(db, season):
    from src.scheduler.calibration import archive
    url=f'https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv'
    async with httpx.AsyncClient(timeout=90,follow_redirects=True) as client:
        response=await client.get(url); response.raise_for_status()
        pbp=await client.get(f'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz')
        pbp.raise_for_status()
    payload=response.text
    rows=list(csv.DictReader(io.StringIO(payload)))
    if not rows or not set(FIELDS.values()).issubset(rows[0]): raise ValueError('missing scoring schema')
    csv_hash=hashlib.sha256(response.content).hexdigest(); now=datetime.now(timezone.utc)
    st,complete=special_teams(csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(pbp.content)))))
    pbp_hash=hashlib.sha256(pbp.content).hexdigest()
    archive('fantasy-special-teams',{'season':season,'sha256':pbp_hash,'counts':{g:dict(v) for g,v in st.items()},'complete_scores':complete})
    digest=hashlib.sha256((csv_hash+pbp_hash).encode()).hexdigest()
    archive('fantasy-scoring-source',{'season':season,'source':url,'sha256':csv_hash,'pbp_sha256':pbp_hash,
        'observation_sha256':digest,'observed_at':now.isoformat(),'rows':rows})
    players={p.gsis_id:p.id for p in (await db.scalars(select(Player).where(Player.sport=='nfl',Player.gsis_id.isnot(None)))).all()}
    teams={t.id:t.nflverse_abbr for t in (await db.scalars(select(Team).where(Team.sport=='nfl'))).all()}
    alias={'LA':'LAR','WSH':'WAS','JAC':'JAX'}
    norm=lambda x:alias.get(x,x)
    games=(await db.scalars(select(Game).where(Game.sport=='nfl',Game.season==season,Game.status=='final',
        Game.game_time.isnot(None),Game.game_time<now))).all()
    by_key=defaultdict(list)
    for g in games:
        by_key[(g.week,norm(teams.get(g.home_team_id)),norm(teams.get(g.away_team_id)))].append(g)
    grouped=defaultdict(dict); skipped=0; skip_reasons=Counter(); unresolved=[]
    for row in rows:
        if int(row['season'])!=season or row['season_type']!='REG': continue
        parts=row['game_id'].split('_')
        matches=by_key.get((int(row['week']),norm(parts[-1]),norm(parts[-2])),[])
        pid=players.get(row['player_id'])
        if len(matches)!=1 or pid is None:
            reason='missing_or_ambiguous_final_game' if len(matches)!=1 else 'missing_exact_gsis_identity'
            skipped+=1; skip_reasons[reason]+=1
            unresolved.append({'provider_game_id':row['game_id'],'gsis_id':row['player_id'],'reason':reason})
            continue
        g=matches[0]
        if g.nflverse_game_id and g.nflverse_game_id!=row['game_id']:
            skipped+=1; skip_reasons['game_identity_conflict']+=1
            unresolved.append({'provider_game_id':row['game_id'],'gsis_id':row['player_id'],'reason':'game_identity_conflict'})
            continue
        if pid in grouped[g.id]: raise ValueError('duplicate player game')
        values=parse(row)
        if complete.get(row['game_id'])==(g.home_score,g.away_score):
            special=st.get(row['game_id'],{}).get(row['player_id'],{'special_teams_ff':0,'special_teams_fum_rec':0,
                'defensive_conversion_returns':0,'one_point_safeties':0})
            # Reconcile the ST subset against full-game published player totals.
            if (row.get('def_fumbles_forced') not in (None,'') and row.get('fumble_recovery_opp') not in (None,'')
                and special['special_teams_ff']<=float(row['def_fumbles_forced'])
                and special['special_teams_fum_rec']<=float(row['fumble_recovery_opp'])):
                values.update(special)
        grouped[g.id][pid]=values
    written=waiting=applied=0
    disagreements=[]
    provider='nflverse_fantasy'
    for gid,parsed in grouped.items():
        facts={(f.player_id,f.stat_type):f for f in (await db.scalars(select(PlayerGameStat).where(
            PlayerGameStat.game_id==gid).with_for_update())).all()}
        pending={p.stat_id:p for p in (await db.scalars(select(ResultCorrection).join(PlayerGameStat,
            PlayerGameStat.id==ResultCorrection.stat_id).where(PlayerGameStat.game_id==gid,
                ResultCorrection.provider==provider,ResultCorrection.status=='pending'))).all()}
        confirmed={}
        for correction in (await db.scalars(select(ResultCorrection).join(PlayerGameStat,
            PlayerGameStat.id==ResultCorrection.stat_id).where(PlayerGameStat.game_id==gid,
                ResultCorrection.provider=='espn_nfl',ResultCorrection.status=='applied')
                .order_by(ResultCorrection.applied_at.desc(),ResultCorrection.id))).all():
            confirmed.setdefault(correction.stat_id,correction.new_value)
        additions=[]
        for pid,values in parsed.items():
            for stat,value in values.items():
                fact=facts.get((pid,stat))
                if fact is None:
                    additions.append({'player_id':pid,'game_id':gid,'stat_type':stat,'value':value})
                else:
                    if preserve_confirmed_boxscore(fact,confirmed):
                        if value!=fact.value:
                            disagreements.append({'game_id':str(gid),'player_id':str(pid),'stat':stat,
                                'retained_value':fact.value,'supplemental_value':value})
                        if fact.id in pending:
                            pending[fact.id].status='superseded'
                            pending[fact.id].last_seen_at=now
                            pending[fact.id].last_payload_hash=digest
                        continue
                    proposal,changed=observe(fact,pending.get(fact.id),value,provider,str(gid),digest,now)
                    if proposal is not None: db.add(proposal); waiting+=proposal.status=='pending'
                    applied+=changed
        if additions:
            result=await db.execute(insert(PlayerGameStat).values(additions).on_conflict_do_nothing(
                index_elements=['player_id','game_id','stat_type']).returning(PlayerGameStat.id))
            written+=len(result.all())
    archive('fantasy-scoring-disagreements',{'observed_at':now.isoformat(),'season':season,
        'policy':'preserve_confirmed_espn_value_v1','source_sha256':digest,'rows':disagreements})
    await db.commit()
    archive('fantasy-scoring-unresolved',{'observed_at':now.isoformat(),'season':season,
        'source_sha256':digest,'counts':dict(skip_reasons),'rows':unresolved})
    return {'season':season,'games':len(grouped),'rows_written':written,'unmapped_rows':skipped,
        'unmapped_reasons':dict(skip_reasons),
        'corrections_pending':waiting,'corrections_applied':applied,'sha256':digest,
        'preserved_boxscore_disagreements':len(disagreements)}
