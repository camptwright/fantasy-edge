"""Exact-league provider totals, separate from component-scored model history."""
import hashlib
import json
from collections import defaultdict
from datetime import timedelta
from sqlalchemy import select, or_
from src.models.base import utcnow
from src.models.facts import Game
from src.models.sleeper import SleeperLeagueSnapshot
from src.services.roster_stat_model import finite

KIND = 'scored_history'


def scoring_hash(scoring, official_rules=None):
    contract=scoring if official_rules is None else {'scoring':scoring,'official_rules':official_rules}
    return hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def exact_totals(rows):
    """No sum across duplicate roster appearances; disagreement excludes player."""
    values = defaultdict(list)
    for row in rows:
        for pid, value in row.get('players_points', {}).items():
            values[str(pid)].append(value)
    return {pid: float(v[0]) for pid, v in values.items()
            if all(finite(x) for x in v) and len(set(v)) == 1}


async def collect(db, client, league, *, now=None):
    """Called only after successful live Sleeper league/rules refresh."""
    from src.services.fantasy_schedule import coverage
    from src.ingest.sleeper import _snapshot
    now = now or utcnow()
    games = list((await db.scalars(select(Game).where(Game.sport == 'nfl',
        Game.season == int(league['season']), or_(Game.game_type.is_(None), Game.game_type == 'REG')))).all())
    if not coverage(games)['complete']:
        return {'status': 'incomplete_schedule', 'weeks': 0}
    written = 0
    for week in sorted({g.week for g in games if g.week and 1 <= g.week <= 18}):
        slate = [g for g in games if g.week == week]
        if not all(g.status == 'final' and g.game_time and g.game_time < now-timedelta(hours=24) for g in slate):
            continue
        old = await db.get(SleeperLeagueSnapshot, (league['league_id'], week, KIND))
        digest = scoring_hash(league['scoring_settings'])
        if old and old.payload.get('scoring_hash') == digest and timedelta(0) <= now-old.synced_at < timedelta(days=1):
            continue
        response = await client.get(f"/league/{league['league_id']}/matchups/{week}")
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or not rows:
            continue
        points = exact_totals(rows)
        if not points:
            continue
        await _snapshot(db, league['league_id'], week, KIND, {
            'schema_version': 1, 'season': str(league['season']), 'week': week,
            'scoring_hash': digest, 'observed_at': now.isoformat(), 'points': points,
            'scoring_contract':league['scoring_settings'],
            'game_ids': sorted(str(g.id) for g in slate),
            'source': 'sleeper_league_matchup_players_points',
            'scope': 'provider_weekly_totals_not_independently_reconstructed_boxscores'})
        # Refresh final result snapshots used by prospective grading too.
        await _snapshot(db, league['league_id'], week, 'matchups', rows)
        written += 1
    return {'status': 'collected', 'weeks': written}


def distributions(snapshots, scoring, season, week, now, official_rules=None):
    """No cross-league, cross-rule, current/future-week or future-observed data."""
    result = defaultdict(list)
    digest = scoring_hash(scoring,official_rules)
    for row in sorted(snapshots, key=lambda s: s.week):
        p = row.payload
        if (row.kind != KIND or row.week >= week or row.synced_at > now or
            p.get('schema_version') != 1 or p.get('season') != str(season) or p.get('scoring_hash') != digest):
            continue
        for pid, value in p.get('points', {}).items():
            if finite(value):
                result[str(pid)].append({'week': row.week, 'points': value,
                    'observed_at': row.synced_at.isoformat()})
    return {pid: {'source': 'league_scored_provider_history', 'games': len(rows),
        'status': 'estimated_distribution' if len(rows) >= 8 else 'insufficient_history',
        'scoring_hash': digest, 'evidence': rows,
        'score_samples': [r['points'] for r in rows] if len(rows) >= 8 else []}
        for pid, rows in result.items()}


async def collect_espn(db, league_id, season, scoring, payload, now=None, *, client=None, raw_league_id=None):
    """Archive only actual weekly applied totals in the authenticated league payload."""
    from src.services.fantasy_schedule import coverage
    from src.ingest.espn_fantasy import _snapshot
    now=now or utcnow()
    rules=payload.get('settings',{}).get('scoringSettings')
    if not rules:return {'status':'missing_official_rules','weeks':0}
    games=list((await db.scalars(select(Game).where(Game.sport=='nfl',Game.season==season,
        or_(Game.game_type.is_(None),Game.game_type=='REG')))).all())
    if not coverage(games)['complete']:return {'status':'incomplete_schedule','weeks':0}
    written=0
    digest=scoring_hash(scoring,rules)
    for week in sorted({g.week for g in games if g.week and 1<=g.week<=18}):
        slate=[g for g in games if g.week==week]
        if not all(g.status=='final' and g.game_time and g.game_time<now-timedelta(hours=24) for g in slate):continue
        old=await db.get(SleeperLeagueSnapshot,(league_id,week,KIND))
        matchup = await db.get(SleeperLeagueSnapshot, (league_id, week, 'matchups'))
        pool = await db.get(SleeperLeagueSnapshot, (league_id, week, 'historical_player_scores')) if client is not None else None
        pool_fresh = client is None or (pool is not None
            and isinstance(pool.payload, dict)
            and pool.payload.get('scoring_hash') == digest
            and timedelta(0) <= now-pool.synced_at < timedelta(days=1))
        if (old and old.payload.get('scoring_hash')==digest
            and pool_fresh
            and timedelta(0)<=now-old.synced_at<timedelta(days=1)
            and matchup and timedelta(0)<=now-matchup.synced_at<timedelta(days=1)
            and matchup.synced_at>=max(g.game_time for g in slate)+timedelta(hours=24)):continue
        historical=payload
        if client is not None:
            response=await client.get(f'/seasons/{season}/segments/0/leagues/{raw_league_id}',
                params=[('view','mSettings'),('view','mRoster'),('view','mMatchup'),('scoringPeriodId',week)])
            response.raise_for_status()
            historical=response.json()
            if (historical.get('scoringPeriodId')!=week or
                historical.get('settings',{}).get('scoringSettings')!=rules):
                raise ValueError('ESPN historical period or scoring rules do not match')
        rows=[]
        for team in historical.get('teams',[]):
            for entry in team.get('roster',{}).get('entries',[]):
                player=entry.get('playerPoolEntry',{}).get('player',{})
                if player.get('id') is None:continue
                for stat in player.get('stats',[]):
                    if stat.get('statSourceId')==0 and stat.get('scoringPeriodId')==week and stat.get('seasonId')==season:
                        rows.append({'players_points':{str(player['id']):stat.get('appliedTotal')}})
        points=exact_totals(rows)
        if not points:continue
        # Legacy weekly/provider graders consume matchups, not scored_history.
        # Refresh both from the same explicitly requested final period. Preserve
        # previously observed starters rather than inferring historical lineups.
        from src.ingest.espn_fantasy import _parse_matchups
        prior = matchup.payload if matchup and isinstance(matchup.payload, list) else []
        matches = _parse_matchups(historical, week, {r['roster_id']:r.get('starters',[]) for r in prior})
        for row in matches:
            row['players_points'] = {pid:points[pid] for pid in row['players_points'] if pid in points}
        if matches and historical.get('scoringPeriodId') == week:
            await _snapshot(db, league_id, week, 'matchups', matches)
        await _snapshot(db,league_id,week,KIND,{'schema_version':1,'season':str(season),'week':week,
            'scoring_hash':digest,'observed_at':now.isoformat(),'points':points,
            'scoring_contract':{'scoring':scoring,'official_rules':rules},
            'game_ids':sorted(str(g.id) for g in slate),'source':'espn_league_applied_totals',
            'scope':'exact_requested_period_actuals_not_inferred_roster_history'})
        if client is not None:
            from src.services.fantasy_player_results import collect_espn_pool
            await collect_espn_pool(db,client,league_id=league_id,raw_league_id=raw_league_id,
                season=season,week=week,scoring=scoring,rules=rules,roster_points=points,
                game_ids=[str(g.id) for g in slate],now=now)
        written+=1
    return {'status':'collected','weeks':written}
