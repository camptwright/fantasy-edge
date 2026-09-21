"""Conservative event matching using provider matchup and scheduled time.

Never resolve by the player's current team. Exact full names and kickoff
must identify one fixture; ambiguity and unsupported event kinds stay null.
"""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import aliased
from src.models.facts import Game
from src.models.identity import Team
from src.ingest.identity import _aliases


def event_binding(game):
    """Call only after exact provider matchup/time resolution, never a guess."""
    return {'method': 'exact_matchup_kickoff_v1', 'game_id': str(game.id),
            'sport': game.sport, 'home_team_id': str(game.home_team_id),
            'away_team_id': str(game.away_team_id), 'kickoff': game.game_time.isoformat()}


async def match_priced_event(db, event, sport):
    """Props require an exact unique kickoff, not a 24-hour team-pair window.

    Doubleheaders, duplicate fixtures and schedule disagreement remain parked.
    Do not use current roster membership to guess the provider's event.
    """
    home, away = event.get('home_team'), event.get('away_team')
    if not isinstance(home, str) or not isinstance(away, str):
        return None
    game_id = await resolve_prop_event(db, sport, {
        'full_team_names_title': f'{away} @ {home}',
        'scheduled_at': event.get('commence_time'),
    })
    return await db.get(Game, game_id) if game_id else None


async def resolve_prop_event(db, sport, event):
    if not event:
        return None
    title = event.get('full_team_names_title', '')
    if title.count(' @ ') != 1:
        return None
    try:
        kickoff = datetime.fromisoformat(event['scheduled_at'].replace('Z', '+00:00'))
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
    if kickoff.tzinfo is None:
        return None
    away_name, home_name = title.split(' @ ')
    # Exact configured aliases only; no fuzzy matching or time-window guesses.
    aliases = _aliases(sport)
    def full_name(name):
        name = name.strip()
        return aliases.get(name, {}).get('espn_name', name)
    away_name, home_name = full_name(away_name), full_name(home_name)
    home, away = aliased(Team), aliased(Team)
    games = (await db.scalars(select(Game).join(home, home.id == Game.home_team_id)
        .join(away, away.id == Game.away_team_id).where(
            Game.sport == sport, home.sport == sport, away.sport == sport,
            home.name == home_name.strip(), away.name == away_name.strip(),
            Game.game_time == kickoff,
        ))).all()
    return games[0].id if len(games) == 1 else None
