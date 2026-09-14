"""Game-linked ESPN injury evidence, NOT an official inactive/lineup feed."""
from datetime import datetime, timedelta, timezone
import httpx
from sqlalchemy import or_, select
from config.settings import get_settings
from src.models.facts import Game
from src.data.espn_injuries import athlete_id


def parse(payload, game, observed):
    competitions = payload.get('header', {}).get('competitions', [])
    competition = next((c for c in competitions if str(c.get('id')) == game.espn_event_id), None)
    if competition is None:
        raise ValueError('event identity mismatch')
    kickoff = datetime.fromisoformat(competition['date'].replace('Z', '+00:00'))
    if kickoff.tzinfo is None or game.game_time is None or abs((kickoff-game.game_time).total_seconds()) > 60:
        raise ValueError('event kickoff mismatch')
    team_ids = {str(c['id']) for c in competition.get('competitors', [])}
    if len(team_ids) != 2:
        raise ValueError('event teams missing')
    blocks = payload.get('injuries')
    result = {'game_id': str(game.id), 'event_id': game.espn_event_id, 'sport': game.sport,
        'kickoff': kickoff.isoformat(), 'observed_at': observed.isoformat(),
        'provider': 'espn_event_injuries', 'scope': 'team_injuries_on_event_page',
        'coverage': 'reported' if isinstance(blocks, list) else 'not_provided', 'rows': [],
        'official_game_status_verified': False}
    if blocks is None:
        return result
    if not isinstance(blocks, list):
        raise ValueError('invalid injury section')
    for block in blocks:
        if str(block.get('team', {}).get('id')) not in team_ids:
            raise ValueError('injury team outside event')
        for injury in block.get('injuries', []):
            athlete = injury.get('athlete', {})
            external = str(athlete.get('id') or athlete_id(athlete) or '')
            if not external.isdigit():
                continue
            result['rows'].append({'athlete_id': external, 'status': injury.get('status'),
                'reported_at': injury.get('date'), 'observed_at': observed.isoformat(),
                'provider': 'espn_event_injuries', 'team_id': str(block['team']['id']),
                'game_id': str(game.id), 'sport': game.sport})
    return result


async def collect(db):
    now = datetime.now(timezone.utc)
    games = (await db.scalars(select(Game).where(Game.sport.in_(['nfl', 'ncaaf']),
        Game.status == 'scheduled', Game.espn_event_id.isnot(None),
        or_(Game.game_time.is_(None), Game.game_time >= now),
        or_(Game.game_time.is_(None), Game.game_time <= now+timedelta(days=7)))
        .order_by(Game.game_time.asc().nulls_last(), Game.id).limit(160))).all()
    results = []
    async with httpx.AsyncClient(timeout=8) as client:
        for game in games:
            basic = {'game_id': str(game.id), 'sport': game.sport, 'event_id': game.espn_event_id,
                     'observed_at': datetime.now(timezone.utc).isoformat(), 'rows': []}
            if game.game_time is None:
                results.append({**basic, 'coverage': 'unknown_kickoff'})
                continue
            try:
                response = await client.get(get_settings().espn_base_urls[game.sport]+'/summary',
                                            params={'event': game.espn_event_id})
                response.raise_for_status()
                results.append(parse(response.json(), game, datetime.now(timezone.utc)))
            except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                results.append({**basic, 'coverage': 'fetch_failed'})
    return {'observed_at': datetime.now(timezone.utc).isoformat(), 'games': results}
