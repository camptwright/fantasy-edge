"""Archived, league-bound multiweek research. Never a serving recommendation.

Uses only collected future-week provider projections. Missing categories, future
observations and absent team schedules are unknown, never zero or a repeated
current-week forecast. Final outcomes reuse rule-bound platform score archives.
"""
import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, or_, text
from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.facts import Game
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot
from src.models.identity import Team
from src.services.fantasy_score_history import scoring_hash
from src.services.fantasy_schedule import coverage
from src.services.retention_research import compare, grade_frozen
from src.services.roster_stat_model import finite
from src.services.roster_stat_prospective import publish

RECIPE = 'retention_provider_horizon_v2'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def publish_latest(root, report):
    """Atomic compact pointer; immutable evidence remains in reports/forecasts."""
    folder = Path(root)/'latest'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder/(hashlib.sha256(report['league_id'].encode()).hexdigest()+'.json')
    compact = {k: v for k, v in report.items() if k != 'grades'}
    compact['grade_counts'] = dict(Counter(row['status'] for row in report['grades']))
    fd, temporary = tempfile.mkstemp(prefix='.retention-', dir=folder)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(compact, stream, sort_keys=True)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def recipe_hash():
    directory = Path(__file__).parent
    return digest({name: hashlib.sha256((directory/name).read_bytes()).hexdigest()
                   for name in ('retention_pipeline.py', 'retention_research.py')})


def projection_points(stats, scoring, platform):
    if not isinstance(stats, dict):
        return None
    if platform == 'espn':
        return float(stats['_espn_applied_total']) if finite(stats.get('_espn_applied_total')) else None
    weights = {k: v for k, v in scoring.items() if finite(v) and v != 0}
    # Sparse provider projections are not permission to invent omitted zeros.
    if not weights or any(not finite(stats.get(k)) for k in weights):
        return None
    return round(sum(stats[k]*v for k, v in weights.items()), 4)


def adapt(lab, league, snapshots, games, teams, weeks, now):
    """Bind provider IDs to the saved player pool and unique team/week events."""
    aliases = {'LA': 'LAR', 'JAC': 'JAX', 'WSH': 'WAS'}
    index = {}
    for team in teams:
        key = aliases.get(team.nflverse_abbr, team.nflverse_abbr)
        index.setdefault(key, []).append(team.id)
    season_games = [g for g in games if g.season == int(league.season) and g.sport == 'nfl'
                    and getattr(g, 'game_type', None) in (None, 'REG')]
    schedule = coverage(season_games)
    rows = {s.week: s for s in snapshots if s.kind == 'projections' and s.league_id == league.league_id}
    contract = lab.get('scoring_contract_hash') or scoring_hash(league.scoring_settings)
    players = []; bindings = {str(w): {} for w in weeks}; blockers = Counter()
    for p in lab['players']:
        future = {}
        tids = index.get(aliases.get(p.get('team'), p.get('team')), [])
        for week in weeks:
            if len(tids) != 1:
                blockers['unresolved_team'] += 1
                continue
            events = [g for g in season_games if g.week == week and tids[0] in (g.home_team_id, g.away_team_id)]
            if not events and week in schedule['bye_weeks'].get(str(tids[0]), []):
                future[week] = {'status': 'verified_bye'}
                continue
            if len(events) != 1 or not events[0].game_time or events[0].status != 'scheduled' or events[0].game_time <= now+timedelta(minutes=5):
                blockers['unbound_or_started_game'] += 1
                continue
            row = rows.get(week)
            if row is None or not timedelta(0) <= now-row.synced_at <= timedelta(hours=6):
                blockers['missing_or_stale_week_projection'] += 1
                continue
            raw = row.payload if isinstance(row.payload, dict) else {
                str(r['player_id']): r.get('stats', {}) for r in row.payload if isinstance(r, dict) and r.get('player_id')}
            points = projection_points(raw.get(p['player_id']), league.scoring_settings, league.platform)
            if points is None:
                blockers['incomplete_scoring_projection'] += 1
                continue
            future[week] = {'status': 'full_scoring_projection', 'points': points,
                            'observed_at': row.synced_at.isoformat()}
            bindings[str(week)][p['player_id']] = {'game_id': str(events[0].id),
                'kickoff': events[0].game_time.isoformat(), 'team_id': str(tids[0]),
                'projection_observed_at': row.synced_at.isoformat()}
        players.append({**p, 'future_weeks': future})
    return players, bindings, dict(blockers), contract


def freeze(lab, league, snapshots, games, teams, weeks, now):
    if lab.get('status') != 'candidate' or lab.get('coverage', {}).get('stale_inputs'):
        return [], {'stale_or_missing_model': 1}
    if not weeks or any(w not in range(1, 19) for w in weeks) or len(set(weeks)) != len(weeks):
        raise ValueError('Unique NFL regular-season weeks required')
    players, bindings, blockers, contract = adapt(lab, league, snapshots, games, teams, weeks, now)
    by_id = {p['player_id']: p for p in players}
    mine = [r for r in lab['rosters'] if r['is_mine']]
    if len(mine) != 1 or any(pid not in by_id for pid in mine[0]['player_ids']):
        return [], {'unbound_roster': 1}
    roster = [by_id[pid] for pid in mine[0]['player_ids']]
    owned = {pid for r in lab['rosters'] for pid in r['player_ids']}
    records = []
    for move in lab.get('waivers', {}).get('moves', [])[:15]:
        add = by_id.get(move['add_id'])
        if not add or move['add_id'] in owned:
            continue
        forecast = compare(roster, add, move['drop_id'], lab['roster_positions'], weeks)
        if forecast['status'] != 'conditional_research':
            reason = forecast['reason']; blockers[reason] = blockers.get(reason, 0)+1
            continue
        key = {'recipe': RECIPE, 'recipe_hash': recipe_hash(), 'model_version': lab['recipe_version'], 'league_id': league.league_id,
               'season': str(league.season), 'weeks': sorted(weeks), 'scoring_contract': contract,
               'roster': sorted(mine[0]['player_ids']), 'add_id': move['add_id'], 'drop_id': move['drop_id']}
        records.append({**key, 'id': digest(key), 'captured_at': now.isoformat(),
            'forecast': forecast, 'player_games': bindings, 'scoring_settings': league.scoring_settings,
            'serving_promoted': False})
    return records, blockers


def outcomes(record, snapshots, games, now):
    """Require exact season/week/rules/event and a final provider archive."""
    result = {}
    game_index = {str(g.id): g for g in games}
    for row in snapshots:
        p = row.payload
        if (row.kind != 'scored_history' or row.league_id != record['league_id'] or not isinstance(p, dict)
            or p.get('schema_version') != 1 or p.get('season') != record['season']
            or p.get('week') != row.week or p.get('scoring_hash') != record['scoring_contract']
            or row.synced_at > now):
            continue
        contract = p.get('scoring_contract')
        if not isinstance(contract, dict):
            continue
        actual_hash = scoring_hash(contract.get('scoring'), contract['official_rules']) if 'official_rules' in contract else scoring_hash(contract)
        if actual_hash != record['scoring_contract']:
            continue
        for pid, evidence in record['player_games'].get(str(row.week), {}).items():
            game = game_index.get(evidence['game_id'])
            if (not game or game.status != 'final' or not game.game_time or game.week != row.week
                or str(game.season) != record['season'] or str(game.id) not in p.get('game_ids', [])
                or game.game_time.isoformat() != evidence['kickoff']
                or row.synced_at < game.game_time+timedelta(hours=24)):
                continue
            points = p.get('points', {}).get(pid)
            if finite(points):
                result[(row.week, pid)] = {'status': 'final', 'points': points,
                    'observed_at': row.synced_at.isoformat(), 'game_id': str(game.id),
                    'league_id': record['league_id'], 'scoring_contract': record['scoring_contract']}
    return result


def planning_weeks(current_week, games, now, horizon):
    """Whole-week scenarios cannot be captured after any part of that slate began."""
    started=any(g.week==current_week and (g.status not in ('scheduled','postponed')
        or (g.game_time is not None and g.game_time<=now+timedelta(minutes=5))) for g in games)
    start=current_week+int(started)
    return list(range(start,min(19,start+horizon)))


async def run_league(db, lab, league, root, *, now=None, horizon=3):
    if not 1 <= horizon <= 6:
        raise ValueError('Bounded research horizon must be 1–6 weeks')
    now = now or datetime.now(timezone.utc)
    snapshots = list((await db.scalars(select(SleeperLeagueSnapshot).where(SleeperLeagueSnapshot.league_id == league.league_id))).all())
    games = list((await db.scalars(select(Game).where(Game.sport == 'nfl', Game.season == int(league.season), or_(Game.game_type.is_(None), Game.game_type == 'REG')))).all())
    teams = list((await db.scalars(select(Team).where(Team.sport == 'nfl'))).all())
    weeks = planning_weeks(lab.get('week',1),games,now,horizon)
    records, blockers = freeze(lab, league, snapshots, games, teams, weeks, now) if weeks else ([],{'no_future_regular_season_weeks':1})
    # A separately identified shorter horizon is useful evidence, not a claim
    # that the requested longer horizon is complete. Never reduce to one week.
    horizon_captures = {str(len(weeks)): len(records)}
    for size in range(2, len(weeks)):
        shorter, _ = freeze(lab, league, snapshots, games, teams, weeks[:size], now)
        records.extend(shorter)
        horizon_captures[str(size)] = len(shorter)
    root = Path(root)
    written = sum(publish(root/'forecasts'/f"{r['id']}.json", r) for r in records)
    grades = []
    for path in sorted((root/'forecasts').glob('*.json')):
        record = json.loads(path.read_text())
        if record['league_id'] != league.league_id or record['season'] != str(league.season):
            continue
        grades.append({'id': record['id'], **grade_frozen(record, outcomes(record, snapshots, games, now))})
    report = {'league_id': league.league_id, 'season': str(league.season),
        'generated_at': now.isoformat(), 'recipe': RECIPE, 'recipe_hash': recipe_hash(),
        'forecast_count': len(grades),
        'requested_weeks': weeks, 'new_captures': written, 'capture_blockers': blockers,
        'eligible_scenarios_by_horizon_weeks': horizon_captures,
        'available_projection_weeks': sorted({s.week for s in snapshots if s.kind == 'projections'
            and timedelta(0) <= now-s.synced_at <= timedelta(hours=6)}),
        'grades': grades, 'serving_promoted': False,
        'scope': 'Frozen conditional lineup scenarios; not full-season value, transaction advice or independent qualification.'}
    publish(root/'reports'/f"{now.strftime('%Y%m%dT%H%M%S%f')}-{league.league_id.replace(':', '_')}.json", report)
    publish_latest(root, report)
    return report


async def execute():
    from src.services.fantasy_decision_models import build
    root = Path(get_settings().raw_archive_dir)/'fantasy-retention'
    async with get_worker_db() as db:
        await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        leagues = list((await db.scalars(select(SleeperLeague).where(SleeperLeague.sport == 'nfl'))).all())
        return [await run_league(db, await build(db, league.league_id), league, root) for league in leagues]
