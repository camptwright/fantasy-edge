"""Seed only provider-native boxscore identities, never match historical names."""
from sqlalchemy import select, text
from src.models.identity import Player, PlayerExternalId


def identities(payload, sport):
    people = {}
    if sport == 'mlb':
        rows = [p for t in payload.get('boxscore', {}).get('teams', {}).values() for p in t.get('players', {}).values()]
        candidates = [(p.get('person', {}), p.get('position', {})) for p in rows]
    elif sport in ('ncaaf', 'nba'):
        candidates = [(r.get('athlete', {}), r.get('athlete', {}).get('position', {}))
            for t in payload.get('boxscore', {}).get('players', []) for s in t.get('statistics', [])
            for r in s.get('athletes', []) if not r.get('didNotPlay')]
    else:
        return people  # NFL requires its existing GSIS crosswalk.
    for person, position in candidates:
        pid = str(person.get('id', ''))
        name = person.get('fullName') or person.get('displayName')
        if not pid.isdigit() or not isinstance(name, str) or not 0 < len(name.strip()) <= 128:
            continue
        value = (name.strip(), position.get('abbreviation'))
        if pid in people and people[pid][0] != value[0]:
            raise ValueError('conflicting provider identity')
        people[pid] = value
    return people


async def seed_participants(db, sport, provider, payload, parsed):
    expected = {'mlb': 'mlb_stats_api', 'ncaaf': 'espn_ncaaf', 'nba': 'espn_nba'}
    if expected.get(sport) != provider:
        return 0
    count = 0
    known = set((await db.scalars(select(PlayerExternalId.external_id).where(
        PlayerExternalId.source == provider, PlayerExternalId.external_id.in_(parsed)))).all())
    for external, (name, position) in sorted(identities(payload, sport).items()):
        if external not in parsed or external in known:
            continue
        # Concurrent games can contain the same player. Lock in sorted order.
        await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                         {'key': provider+':'+external})
        existing = await db.scalar(select(PlayerExternalId).where(
            PlayerExternalId.source == provider, PlayerExternalId.external_id == external))
        if existing:
            continue
        player = Player(sport=sport, full_name=name,
                        position=position if isinstance(position, str) and len(position) <= 8 else None)
        db.add(player)
        await db.flush()
        db.add(PlayerExternalId(player_id=player.id, source=provider, external_id=external))
        await db.flush()
        count += 1
    return count
