"""Official NHL player identity and completed-game result backfill.

Boxscore names are abbreviated; full identities come from /player/{id}/landing.
Only positive recorded time-on-ice establishes participation. No season stats,
unplayed goalkeeper zeros, or missing fields become realized outcomes.
"""
import math
from sqlalchemy import select
from config.settings import get_settings
from src.models.identity import Player, PlayerExternalId

SOURCE = 'nhl_api'
SKATER = {'goals': 'goals', 'assists': 'assists', 'points': 'points',
          'sog': 'shots_on_goal', 'hits': 'hits', 'blockedShots': 'blocked_shots',
          'pim': 'penalty_minutes', 'powerPlayGoals': 'power_play_goals'}
GOALIE = {'saves': 'saves', 'shotsAgainst': 'shots_against', 'goalsAgainst': 'goals_against'}


def ice_seconds(value):
    try:
        minutes, seconds = value.split(':')
        minutes, seconds = int(minutes), int(seconds)
        return minutes*60+seconds if minutes >= 0 and 0 <= seconds < 60 else None
    except (AttributeError, ValueError, TypeError):
        return None


def participants(payload):
    for side in ('homeTeam', 'awayTeam'):
        groups = payload.get('playerByGameStats', {}).get(side, {})
        for category in ('forwards', 'defense', 'goalies'):
            for row in groups.get(category, []):
                seconds = ice_seconds(row.get('toi'))
                if not row.get('playerId') or not seconds:
                    continue
                stats = {'time_on_ice_seconds': float(seconds)}
                for field, canonical in (GOALIE if category == 'goalies' else SKATER).items():
                    value = row.get(field)
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                        stats[canonical] = float(value)
                yield str(row['playerId']), stats


async def identity(db, client, external_id):
    from sqlalchemy import text
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                     {'key': SOURCE + ':' + external_id})
    mapped = await db.scalar(select(PlayerExternalId).where(
        PlayerExternalId.source == SOURCE, PlayerExternalId.external_id == external_id))
    if mapped is not None:
        player = await db.get(Player, mapped.player_id)
        if player is None or player.sport != 'nhl':
            raise ValueError('NHL identity crosswalk has incorrect sport')
        return player.id
    response = await client.get(f'{get_settings().nhl_api_base_url}/player/{external_id}/landing')
    response.raise_for_status()
    profile = response.json()
    first = profile.get('firstName', {}).get('default')
    last = profile.get('lastName', {}).get('default')
    if str(profile.get('playerId')) != external_id or not first or not last:
        raise ValueError('Incomplete or mismatched NHL player profile')
    player = Player(sport='nhl', full_name=f'{first} {last}', position=profile.get('position'))
    db.add(player)
    await db.flush()
    db.add(PlayerExternalId(source=SOURCE, external_id=external_id, player_id=player.id))
    await db.flush()
    return player.id


async def sync_nhl_results(db, limit=20, *, game_ids=None, refresh=False):
    from src.ingest.result_repair import sync_results
    async def fetch(client, event_id):
        response = await client.get(f'{get_settings().nhl_api_base_url}/gamecenter/{event_id}/boxscore')
        response.raise_for_status()
        payload = response.json()
        if str(payload.get('id')) != event_id or payload.get('gameState') not in ('OFF', 'FINAL'):
            raise ValueError('NHL boxscore is not the requested final game')
        for side in ('homeTeam', 'awayTeam'):
            groups = payload.get('playerByGameStats', {}).get(side, {})
            if not all(isinstance(groups.get(g), list) and groups[g] for g in ('forwards', 'defense', 'goalies')):
                raise ValueError('Incomplete NHL boxscore groups')
        parsed = {}
        for external, stats in participants(payload):
            if external in parsed:
                raise ValueError('Duplicate NHL participant')
            parsed[external] = stats
        if not parsed:
            raise ValueError('NHL boxscore has no participants')
        return payload, parsed
    async def prepare(db, client, payload, parsed):
        for external in sorted(parsed):
            await identity(db, client, external)
    return await sync_results(db, 'nhl', SOURCE, 'nhl_game_id', fetch, limit,
                              game_ids=game_ids, refresh=refresh, prepare=prepare)
