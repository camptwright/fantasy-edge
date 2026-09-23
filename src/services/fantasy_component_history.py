"""Observed Sleeper weekly actuals, not point-in-time historical forecasts.

Sparse zero reconstruction is permitted only for a bounded scoring vocabulary
and must reconcile against exact current-league totals before research use.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from sqlalchemy import select
from src.models.base import utcnow
from src.models.facts import Game
from src.models.identity import Team
from src.models.sleeper import SleeperLeagueSnapshot
from src.services.fantasy_score_history import KIND, scoring_hash
from src.services.roster_stat_model import finite

ARCHIVE_ID = '__sleeper_nfl_actuals__'
PREFIX = 'actual_components_'
SUPPORTED = set('pass_yd pass_td pass_int pass_2pt rush_yd rush_td rush_2pt rec rec_yd rec_td rec_2pt fum fum_lost fum_rec_td st_td st_ff st_fum_rec int sack safe def_td fum_rec ff blk_kick xpm xpmiss fgmiss fgm_0_19 fgm_20_29 fgm_30_39 fgm_40_49 fgm_50p fgm_50_59 fgm_60p def_st_td def_st_ff def_st_fum_rec pts_allow_0 pts_allow_1_6 pts_allow_7_13 pts_allow_14_20 pts_allow_21_27 pts_allow_28_34 pts_allow_35p'.split())


def total(row, scoring):
    if not scoring or not any(scoring.values()) or any(not finite(v) or (v and k not in SUPPORTED) for k,v in scoring.items()):
        return None
    stats = row.get('stats', {})
    if not isinstance(stats, dict) or stats.get('gp') != 1:
        return None
    if any(not finite(stats[k]) for k in scoring if k in stats):
        return None
    return sum(stats.get(k, 0) * v for k,v in scoring.items())


def bound_rows(payload, season, week, slate, abbreviations):
    """Exact season/week, played appearance, opponent and dated final game."""
    if not isinstance(payload, list):
        raise ValueError('unexpected weekly actuals shape')
    result = {}; conflicts = set()
    for row in payload:
        if (not isinstance(row,dict) or row.get('category') != 'stat' or
            str(row.get('season')) != str(season) or row.get('week') != week or
            row.get('sport') != 'nfl' or row.get('season_type') != 'regular' or
            not row.get('player_id') or row.get('stats',{}).get('gp') != 1):
            continue
        team = abbreviations.get(row.get('team')); opponent = abbreviations.get(row.get('opponent'))
        matched = [g for g in slate if team and opponent and team != opponent and
            {g.home_team_id,g.away_team_id} == {team,opponent} and g.game_time and
            row.get('date') in {g.game_time.date().isoformat(), (g.game_time-timedelta(hours=6)).date().isoformat()}]
        if len(matched) != 1:
            continue
        pid = str(row['player_id'])
        record = {'player_id':pid,'position':row.get('player',{}).get('position'),
            'stats':row['stats'],'game_id':str(matched[0].id),
            'kickoff':matched[0].game_time.isoformat(),'provider_game_id':row.get('game_id')}
        if pid in result and result[pid] != record:
            conflicts.add(pid)
        result[pid] = record
    return {pid:r for pid,r in result.items() if pid not in conflicts}


async def collect(db, client, season, *, now=None):
    """Shared archive: two seasons, daily corrections, only completed slates."""
    from src.ingest.sleeper import _snapshot
    now = now or utcnow(); written = 0
    teams = (await db.scalars(select(Team).where(Team.sport == 'nfl'))).all()
    abbr = {t.nflverse_abbr:t.id for t in teams if t.nflverse_abbr}
    for alias, canonical in {'LA':'LAR','JAC':'JAX','WSH':'WAS'}.items():
        if canonical in abbr: abbr[alias] = abbr[canonical]
    games = (await db.scalars(select(Game).where(Game.sport == 'nfl',
        Game.season.in_([int(season)-1,int(season)]), Game.game_type == 'REG'))).all()
    for year, week in sorted({(g.season,g.week) for g in games if g.week and 1 <= g.week <= 18}):
        slate = [g for g in games if g.season == year and g.week == week]
        # Unknown dates/status never become eligible by falling out of a query.
        if not all(g.status == 'final' and g.game_time and g.game_time < now-timedelta(hours=24) for g in slate):
            continue
        kind = PREFIX+str(year)
        old = await db.get(SleeperLeagueSnapshot,(ARCHIVE_ID,week,kind))
        interval = timedelta(days=30 if year < int(season) else 1)
        if old and timedelta(0) <= now-old.synced_at < interval:
            continue
        response = await client.get(f'https://api.sleeper.com/stats/nfl/{year}/{week}',params={'season_type':'regular'})
        response.raise_for_status()
        rows = bound_rows(response.json(),year,week,slate,abbr)
        if not rows: continue
        await _snapshot(db,ARCHIVE_ID,week,kind,{'schema_version':1,'season':year,'week':week,
            'observed_at':now.isoformat(),'source':'sleeper_weekly_actual_components',
            'scope':'corrected_history_not_point_in_time_forecasts','players':rows})
        written += 1
    return {'weeks':written}


def distributions(archives, official, scoring, season, week, now):
    """Only K/DEF research distributions with same-position scoring reconciliation.

    Reconciliation proves scoring parity, NOT forecast calibration. Each
    source game is retained once; future/current weeks cannot enter history.
    """
    digest = scoring_hash(scoring); evidence = defaultdict(dict); checks = defaultdict(dict)
    official_by_week = {r.week:r.payload for r in official if r.kind == KIND and
        r.synced_at <= now and r.payload.get('season') == str(season) and
        r.payload.get('scoring_hash') == digest and r.week < week}
    for archive in archives:
        data=archive.payload; year=data.get('season'); w=data.get('week')
        if (archive.synced_at > now or data.get('schema_version') != 1 or
            year not in (int(season)-1,int(season)) or not isinstance(w,int) or not 1<=w<=18 or
            (year==int(season) and w>=week)):
            continue
        for pid,row in data.get('players',{}).items():
            position=row.get('position'); value=total(row,scoring)
            if position not in ('K','DEF') or value is None: continue
            if not row.get('game_id') or datetime.fromisoformat(row['kickoff']) >= now: continue
            if year==int(season) and pid in official_by_week.get(w,{}).get('points',{}):
                actual=official_by_week[w]['points'][pid]
                key=(row['game_id'],pid)
                checks[position][key]=checks[position].get(key,True) and finite(actual) and abs(value-actual)<1e-5
            evidence[pid][row['game_id']]={'season':year,'week':w,'points':value,
                'game_id':row['game_id'],'position':position,'observed_at':archive.synced_at.isoformat()}
    result={}
    for pid,game_rows in evidence.items():
        rows=sorted(game_rows.values(),key=lambda r:(r['season'],r['week']))[-20:]
        comparison=list(checks[rows[0]['position']].values())
        reconciled=len(comparison)>=8 and all(comparison)
        result[pid]={'source':'reconciled_sleeper_component_history','games':len(rows),
            'scoring_hash':digest,'reconciliation_samples':len(comparison),
            'reconciliation_mismatches':sum(not x for x in comparison),
            'status':'estimated_distribution' if reconciled and len(rows)>=8 else 'unverified_distribution',
            'evidence':rows,'score_samples':[r['points'] for r in rows] if reconciled and len(rows)>=8 else [],
            'limitations':['Corrected historical outcomes, not archived pregame forecasts.',
                'Prior-season variance may not transfer to current roles; not calibrated probabilities.']}
    return result
