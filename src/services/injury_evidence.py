"""Timestamped provider evidence; missing reports never imply health."""
import json
from datetime import datetime
from sqlalchemy import select
from src.models.identity import Player, PlayerExternalId


def age(value, as_of):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('timezone required')
    return (as_of-stamp).total_seconds()


def archive_rows(directory, as_of, sport=None):
    paths = sorted(directory.glob('*.json'), reverse=True)[:1]
    if not paths:
        return [], 'missing_archive'
    try:
        payload = json.loads(paths[0].read_text())
        rows = payload.get('rows') if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return [], 'invalid_archive'
    except (OSError, ValueError, TypeError):
        return [], 'invalid_archive'
    if sport:
        rows = [r for r in rows if isinstance(r, dict) and r.get('sport') == sport]
    valid, observed = [], False
    for row in rows:
        try:
            if 0 <= age(row['observed_at'], as_of) <= 3600:
                observed = True
                if 0 <= age(row['reported_at'], as_of) <= 604800:
                    valid.append(row)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue  # one malformed row must not discard other players
    return valid, 'fresh_archive' if observed else ('empty_archive' if not rows else 'stale_archive')


def fresh_rows(directory, as_of):
    return archive_rows(directory, as_of)[0]


async def snapshots(db, props, directory, as_of):
    import uuid
    ids = {p['player_id'] for p in props}
    if not ids:
        return {}
    players = dict((await db.execute(select(Player.id, Player.sport).where(
        Player.id.in_([uuid.UUID(p) for p in ids])))).all())
    sports = {str(pid): sport for pid, sport in players.items()}
    links = (await db.execute(select(PlayerExternalId, Player.sport).join(Player, Player.id == PlayerExternalId.player_id)
        .where(Player.id.in_([uuid.UUID(p) for p in ids])))).all()
    identities = {(sport, link.external_id): str(link.player_id) for link, sport in links
                  if link.source == ('mlb_stats_api' if sport == 'mlb' else 'espn_' + sport)}
    verified = set(identities.values())
    espn, _ = archive_rows(directory, as_of)
    espn_states = {sport: archive_rows(directory, as_of, sport)[1] for sport in ('nfl', 'nba', 'nhl')}
    mlb, mlb_state = archive_rows(directory.parent / 'mlb_availability', as_of)
    result = {}
    for pid in ids:
        sport = sports.get(pid)
        source = 'mlb_stats_api' if sport == 'mlb' else 'espn_public_injuries'
        state = mlb_state if sport == 'mlb' else espn_states.get(sport)
        if sport not in ('nfl', 'nba', 'nhl', 'mlb'):
            status = 'coverage_not_supported'
        elif pid not in verified:
            status = 'missing_provider_identity'
        elif state != 'fresh_archive':
            status = state
        else:
            status = 'no_current_player_report'
        result[pid] = {'status': status, 'provider': source, 'identity_verified': pid in verified,
            'provider_athlete_ids': [external for (sp, external), player in identities.items() if player == pid],
            'reports': [], 'used_for_numeric_adjustment': False,
            'note': 'No report does not establish health, availability, or a starting role.'}
    for row in [r for r in espn if r.get('sport') != 'mlb'] + mlb:
        pid = identities.get((row.get('sport'), row.get('athlete_id')))
        if pid:
            result[pid]['status'] = 'fresh_roster_status' if row.get('provider') == 'mlb_stats_api' else 'fresh_injury_report'
            result[pid]['reports'].append(row)
    return result


def game_snapshots(directory, as_of):
    paths = sorted(directory.glob('*.json'), reverse=True)[:1]
    if not paths:
        return {}
    try:
        payload = json.loads(paths[0].read_text())
        return {r['game_id']: r for r in payload['games']}
    except (OSError, ValueError, TypeError, KeyError):
        return {}


def for_game(context, game, external_ids, events, as_of):
    context = dict(context or {})
    if game is None or game.sport not in ('nfl', 'ncaaf'):
        return context
    availability = {'game_id': str(game.id), 'status': 'not_collected',
        'official_game_status_verified': False, 'hold_recommendation': False}
    context['game_availability'] = availability
    event = events.get(str(game.id))
    if not external_ids:
        availability['status'] = 'missing_provider_identity'
        return context
    if not event:
        return context
    try:
        if not 0 <= age(event['observed_at'], as_of) <= 3600:
            availability['status'] = 'stale_game_evidence'
            return context
        if event['event_id'] != game.espn_event_id:
            availability['status'] = 'event_mismatch'
            return context
        availability['status'] = event['coverage']
        if event['coverage'] != 'reported':
            return context
        if game.game_time is None or datetime.fromisoformat(event['kickoff']) != game.game_time:
            availability['status'] = 'kickoff_changed'
            return context
        reports = []
        for row in event['rows']:
            try:
                if row.get('athlete_id') in external_ids and 0 <= age(row['reported_at'], as_of) <= 604800:
                    reports.append(row)
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
        statuses = {str(r.get('status', '')).strip().lower() for r in reports}
        availability.update({'reports': reports, 'status': 'no_player_report',
            'scope': 'team_injuries_on_event_page',
            'note': 'Event-linked ESPN injury evidence, not an official inactive list. No report does not imply available.'})
        if len(statuses) > 1:
            availability['status'] = 'conflicting_reports'
        elif statuses:
            availability['status'] = {'out': 'reported_out_unconfirmed', 'doubtful': 'reported_doubtful',
                'questionable': 'reported_questionable'}.get(next(iter(statuses)), 'reported_other_status')
        # Risk hold, not a declaration of a bookmaker void or confirmed absence.
        near_game = 0 <= (game.game_time-as_of).total_seconds() <= 86400
        availability['hold_recommendation'] = near_game and availability['status'] in {
            'reported_out_unconfirmed', 'reported_doubtful', 'conflicting_reports'}
    except (KeyError, ValueError, TypeError, AttributeError):
        availability['status'] = 'invalid_game_evidence'
        availability['hold_recommendation'] = False
    return context


def unavailable(context):
    reports = (context or {}).get('reports', [])
    statuses = {r.get('status') for r in reports if r.get('provider') == 'mlb_stats_api'}
    return bool(statuses) and statuses.issubset({'D7', 'D10', 'D15', 'D60', 'ILF'})
