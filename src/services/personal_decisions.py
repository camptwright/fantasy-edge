"""Personal choices with frozen expectations; these records never alter a roster."""
from datetime import datetime, timedelta, timezone
from math import isfinite
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from src.models.governance import ForecastArchive
from src.models.facts import Game
from src.models.sleeper import SleeperLeague, SleeperLeagueSnapshot, SleeperRoster
from src.services.forecast_evidence import digest
from src.services.fantasy_score_history import scoring_hash

KIND = 'fantasy_decision'
POSITIONS = {'FLEX': {'RB', 'WR', 'TE'}, 'SUPER_FLEX': {'QB', 'RB', 'WR', 'TE'},
             'WRRB_FLEX': {'WR', 'RB'}, 'REC_FLEX': {'WR', 'TE'}}


class InvalidDecision(ValueError):
    pass


def finite(value):
    try:
        return type(value) in (int, float) and isfinite(value)
    except OverflowError:
        return False


def stamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def request_key(league_id, request_id):
    return digest({'league_id': league_id, 'request_id': str(uuid.UUID(str(request_id)))})


def freeze(data, league, request, games, *, now):
    """Validate against the current checkpoint, rather than browser-supplied scores."""
    if data.get('status') != 'candidate' or data.get('coverage', {}).get('stale_inputs', True):
        raise InvalidDecision('Current league projections are unavailable; refresh first.')
    if data.get('league_id') != league.league_id or data.get('generated_at') != request['generated_at']:
        raise InvalidDecision('The league snapshot changed; refresh before saving.')
    captured = stamp(data.get('generated_at'))
    if captured is None or not timedelta(0) <= now-captured <= timedelta(minutes=10):
        raise InvalidDecision('The league snapshot expired; refresh before saving.')
    mine = [r for r in data.get('rosters', []) if r.get('is_mine') is True]
    if len(mine) != 1:
        raise InvalidDecision('Your roster could not be resolved.')
    mine = mine[0]
    own = set(map(str, mine.get('player_ids', [])))
    owners = {}
    for roster in data.get('rosters', []):
        for pid in roster.get('player_ids', []):
            owners.setdefault(str(pid), set()).add(str(roster['roster_id']))
    a, b = request['player_ids'], request.get('counterparty_player_ids', [])
    ids = a+b
    if not a or len(set(ids)) != len(ids):
        raise InvalidDecision('Choose distinct players for this decision.')
    action = request['action']
    if action == 'start':
        slots = [s for s in data.get('roster_positions', []) if s not in ('BN', 'IR', 'TAXI')]
        if b or len(a) != len(slots) or not set(a) <= own:
            raise InvalidDecision('A lineup must fill each starting slot with your players.')
    elif action == 'pickup':
        if len(a) != 2 or b or owners.get(a[0]) or a[1] not in own:
            raise InvalidDecision('Select an available add followed by a player from your roster to drop.')
    elif action == 'trade':
        recipient = set.intersection(*(owners.get(pid, set()) for pid in b)) if b else set()
        if len(a) > 6 or not b or not set(a) <= own or len(recipient) != 1 or recipient == {str(mine['roster_id'])}:
            raise InvalidDecision('Give players from your roster and receive players from one other roster.')
    else:
        raise InvalidDecision('Unsupported decision type.')
    by_id = {str(p['player_id']): p for p in data.get('players', [])}
    protected = set(map(str, (mine.get('reserve') or []) + (mine.get('taxi') or []))) | set(data.get('_protected') or {})
    contract = league.scoring_settings if league.platform != 'espn' else {
        'scoring': league.scoring_settings, 'official_rules': league.raw.get('scoringSettings')}
    if league.platform == 'espn' and not contract['official_rules']:
        raise InvalidDecision('Verified league scoring rules are unavailable.')
    contract_hash = scoring_hash(contract)
    if data.get('scoring_contract_hash') != contract_hash:
        raise InvalidDecision('League scoring rules changed; refresh first.')
    participants = []
    for index, pid in enumerate(ids):
        p = by_id.get(pid)
        if not p or pid in protected or len(owners.get(pid, set())) > 1:
            raise InvalidDecision('A selected player is unresolved, protected, or has ambiguous ownership.')
        if p.get('identity_status') != 'exact' and not (p.get('position') in ('DEF', 'DST') and p.get('nfl_team_id')):
            raise InvalidDecision('A selected player lacks verified identity and game linkage.')
        if p.get('locked', True) or p.get('week_game_status') != 'scheduled':
            raise InvalidDecision('Save pregame decisions before any selected player starts.')
        if action == 'start' and p.get('position') not in POSITIONS.get(slots[index], {slots[index]}):
            raise InvalidDecision('A selected player is not eligible for the chosen starting slot.')
        upcoming = [g for g in p.get('next_games', []) if g.get('week') == data.get('week')]
        if len(upcoming) != 1:
            raise InvalidDecision('A selected player lacks one exact game this week.')
        binding = upcoming[0]
        game = games.get(binding['id'])
        if (not game or game.status != 'scheduled' or game.season != int(league.season) or
                game.week != data.get('week') or not game.game_time or game.game_time <= now or
                game.game_time != stamp(binding.get('kickoff'))):
            raise InvalidDecision('A selected game changed; refresh before saving.')
        value = p.get('decision_points')
        if not finite(value):
            value = p.get('weekly_points') if p.get('weekly_evidence', {}).get('status') == 'pregame_provider_projection' else None
        if not finite(value):
            raise InvalidDecision('A selected player has no current finite projection.')
        participants.append({'player_id': pid, 'name': p['name'], 'position': p.get('position'),
            'canonical_player_id': p.get('canonical_player_id'), 'roster_ids': sorted(owners.get(pid, set())),
            'role': 'starter' if action == 'start' else 'add' if action == 'pickup' and index == 0 else
                    'drop' if action == 'pickup' else 'give' if index < len(a) else 'receive',
            'slot': slots[index] if action == 'start' else None, 'game_id': str(game.id),
            'kickoff': game.game_time.isoformat(), 'prediction': float(value),
            'prediction_source': p.get('decision_source', p.get('weekly_evidence', {}).get('source', 'unknown')),
            'ros_points': p.get('ros', {}).get('full_ros_value') if finite(p.get('ros', {}).get('full_ros_value')) else None,
            'injury_status': p.get('injury_status')})
    return {'schema_version': 1, 'id': request_key(league.league_id, request['request_id']),
        'request_id': str(request['request_id']), 'request_hash': digest(request), 'league_id': league.league_id,
        'action': action, 'note': request.get('note', ''), 'season': int(league.season), 'week': data['week'],
        'captured_at': now.isoformat(), 'checkpoint_generated_at': data['generated_at'],
        'model_version': data.get('recipe_version'), 'scoring_contract': contract, 'scoring_hash': contract_hash,
        'participants': participants, 'scope': 'personal_choices_not_platform_transactions_or_causal_trade_results'}


def grade_participant(record, participant, game, result, *, now):
    base = {'player_id': participant['player_id'], 'status': 'awaiting_final', 'actual': None, 'error': None}
    if (game is None or str(game.id) != participant['game_id'] or game.season != record['season'] or
            game.week != record['week'] or game.game_time != stamp(participant['kickoff'])):
        return {**base, 'status': 'game_binding_changed'}
    if stamp(record.get('captured_at')) is None or stamp(record['captured_at']) >= game.game_time:
        return {**base, 'status': 'invalid_capture_time'}
    if game.status != 'final':
        return base
    if result is None:
        return {**base, 'status': 'missing_final_result'}
    p = result.payload
    if (result.league_id != record['league_id'] or result.kind != 'scored_history' or result.week != record['week'] or
            p.get('schema_version') != 1 or p.get('season') != str(record['season']) or p.get('week') != record['week'] or
            p.get('scoring_contract') != record['scoring_contract'] or p.get('scoring_hash') != record['scoring_hash'] or
            scoring_hash(p.get('scoring_contract')) != record['scoring_hash'] or
            participant['game_id'] not in p.get('game_ids', [])):
        return {**base, 'status': 'result_contract_or_game_mismatch'}
    if result.synced_at < game.game_time+timedelta(hours=24) or result.synced_at > now:
        return {**base, 'status': 'awaiting_final_snapshot'}
    actual = p.get('points', {}).get(participant['player_id'])
    if not finite(actual):
        return {**base, 'status': 'missing_player_result'}
    return {**base, 'status': 'graded', 'actual': float(actual),
            'error': round(float(actual)-participant['prediction'], 3), 'observed_at': result.synced_at.isoformat()}


async def create(db, league_id, request, *, now=None):
    now = now or datetime.now(timezone.utc)
    key = request_key(league_id, request['request_id'])
    previous = await db.get(ForecastArchive, (key, KIND))
    if previous:
        if previous.payload.get('request_hash') != digest(request):
            raise InvalidDecision('This request ID already belongs to a different decision.')
        return previous.payload
    league = await db.get(SleeperLeague, league_id)
    if not league or league.sport != 'nfl':
        raise InvalidDecision('NFL league not found.')
    from src.services.fantasy_read_model import read
    data = await read(db, league_id)
    if not data:
        raise InvalidDecision('No current league checkpoint; refresh and retry.')
    mine = [r for r in data.get('rosters', []) if r.get('is_mine') is True]
    live = (await db.scalars(select(SleeperRoster).where(SleeperRoster.league_id == league_id))).all()
    if len(mine) != 1 or {str(r.roster_id): set(map(str, r.players)) for r in live} != {
            str(r['roster_id']): set(map(str, r.get('player_ids', []))) for r in data.get('rosters', [])}:
        raise InvalidDecision('Roster ownership changed; refresh before saving.')
    mine_row = next(r for r in live if str(r.roster_id) == str(mine[0]['roster_id']))
    data = {**data, '_protected': set(map(str, (mine_row.reserve or []) + (mine_row.taxi or [])))}
    game_ids = {g['id'] for p in data.get('players', []) for g in p.get('next_games', []) if g.get('week') == data.get('week')}
    games = {str(g.id): g for g in (await db.scalars(select(Game).where(Game.id.in_([uuid.UUID(gid) for gid in game_ids])))).all()}
    record = freeze(data, league, request, games, now=now)
    statement = insert(ForecastArchive).values(digest=key, kind=KIND, payload=record)
    await db.execute(statement.on_conflict_do_nothing(index_elements=['digest', 'kind']))
    await db.commit()
    saved = await db.get(ForecastArchive, (key, KIND))
    if saved.payload.get('request_hash') != digest(request):
        raise InvalidDecision('This request ID already belongs to a different decision.')
    return saved.payload


async def history(db, league_id, *, limit=50, now=None):
    now = now or datetime.now(timezone.utc)
    rows = (await db.scalars(select(ForecastArchive).where(ForecastArchive.kind == KIND,
        ForecastArchive.payload['league_id'].as_string() == league_id)
        .order_by(ForecastArchive.created_at.desc(), ForecastArchive.digest).limit(min(100, max(1, limit))))).all()
    if not rows:
        return []
    game_ids = {p['game_id'] for row in rows for p in row.payload['participants']}
    games = {str(g.id): g for g in (await db.scalars(select(Game).where(Game.id.in_([uuid.UUID(gid) for gid in game_ids])))).all()}
    results = {}
    out = []
    for row in rows:
        record = row.payload
        week = record['week']
        if week not in results:
            results[week] = await db.get(SleeperLeagueSnapshot, (league_id, week, 'scored_history'))
        out.append({**record, 'outcomes': [grade_participant(record, p, games.get(p['game_id']), results[week], now=now)
                                          for p in record['participants']]})
    return out
