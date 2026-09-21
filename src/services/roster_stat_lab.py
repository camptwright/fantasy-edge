"""Own-roster-only read model with exact identity and bounded history queries."""
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy import select, or_
from src.models.sleeper import SleeperLeague, SleeperRoster, SleeperLeagueSnapshot
from src.models.identity import Player, PlayerExternalId, Team
from src.models.facts import Game, PlayerGameStat
from src.services.result_eligibility import no_pending_correction
from src.services.roster_stat_model import STATS, USAGE, RECIPE, forecast
from src.services.player_identity import resolve_platform_players


async def build(db, league_id=None):
    now = datetime.now(timezone.utc)
    leagues = (await db.scalars(select(SleeperLeague).where(SleeperLeague.sport == 'nfl')
                               .order_by(SleeperLeague.name))).all()
    options = [{'id': l.league_id, 'name': l.name} for l in leagues]
    league = next((l for l in leagues if l.league_id == league_id), None) if league_id else next(iter(leagues), None)
    base = {'status': 'unavailable', 'leagues': options, 'players': [], 'serving_enabled': False, 'recipe': RECIPE}
    if league is None:
        return {**base, 'reason': 'league_not_found'}
    snapshots = (await db.scalars(select(SleeperLeagueSnapshot).where(
        SleeperLeagueSnapshot.league_id == league.league_id,
        SleeperLeagueSnapshot.kind.in_(['account', 'player_metadata'])).order_by(
            SleeperLeagueSnapshot.week.desc(), SleeperLeagueSnapshot.synced_at.desc()))).all()
    latest = {}
    for row in snapshots: latest.setdefault(row.kind, row)
    owner = latest.get('account')
    owner_id = owner.payload.get('user_id') if owner and isinstance(owner.payload, dict) else None
    if not owner_id:
        return {**base, 'reason': 'missing_owner_identity'}
    rosters = (await db.scalars(select(SleeperRoster).where(SleeperRoster.league_id == league.league_id,
                                                          SleeperRoster.owner_id == owner_id))).all()
    if len(rosters) != 1:
        return {**base, 'reason': 'ambiguous_or_missing_owned_roster'}
    roster = rosters[0]
    metadata = latest.get('player_metadata')
    catalog = metadata.payload if metadata and isinstance(metadata.payload, dict) else {}
    roster_ids = list(dict.fromkeys(str(p) for p in roster.players))[:40]
    resolved = await resolve_platform_players(db, league.platform, roster_ids)
    stats = set(s for ss in STATS.values() for s in ss) | set(USAGE.values())
    rows = (await db.execute(select(PlayerGameStat, Game).join(Game, Game.id == PlayerGameStat.game_id).where(
        PlayerGameStat.player_id.in_([p.id for p in resolved.values()]), PlayerGameStat.stat_type.in_(stats),
        Game.sport == 'nfl', Game.status == 'final', Game.game_time < now,
        Game.season >= now.year-2, or_(Game.game_type.is_(None), Game.game_type != 'PRE'), no_pending_correction()))).all() if resolved else []
    histories = defaultdict(dict)
    for stat, game in rows:
        entry = histories[stat.player_id].setdefault(game.id, {'game_id': str(game.id), 'time': game.game_time, 'values': {}})
        entry['values'][stat.stat_type] = stat.value
    teams = (await db.scalars(select(Team).where(Team.sport == 'nfl'))).all()
    aliases = {'LA': 'LAR', 'WSH': 'WAS', 'JAC': 'JAX'}
    team_by_abbr = {aliases.get(t.nflverse_abbr, t.nflverse_abbr): t for t in teams}
    team_by_id = {t.id: t for t in teams}
    games = (await db.scalars(select(Game).where(Game.sport == 'nfl', Game.status == 'scheduled',
        Game.game_time > now, Game.game_time <= now+timedelta(days=10),
        or_(Game.game_type.is_(None), Game.game_type != 'PRE')).order_by(Game.game_time))).all()
    players = []
    from src.services.lab_availability import contexts
    player_games={}
    for pid,player in resolved.items():
        info=catalog.get(pid,{})
        team=team_by_abbr.get(aliases.get(info.get('team'),info.get('team')))
        player_games[player.id]=next((g for g in games if team and team.id in (g.home_team_id,g.away_team_id)),None)
    availability_context=await contexts(db,'nfl',[p.id for p in resolved.values()],player_games,now)
    for pid in roster_ids:
        info, player = catalog.get(pid, {}), resolved.get(pid)
        position = info.get('position')
        team = team_by_abbr.get(aliases.get(info.get('team'), info.get('team')))
        game = next((g for g in games if team and team.id in (g.home_team_id, g.away_team_id)), None)
        opponent = team_by_id.get(game.away_team_id if game.home_team_id == team.id else game.home_team_id) if game else None
        forecasts = [forecast(list(histories[player.id].values()), s, now) for s in STATS.get(position, [])] if player else []
        players.append({'roster_player_id': pid, 'name': ' '.join(str(info.get(k) or '') for k in ('first_name', 'last_name')).strip() or pid,
            'availability_candidate':availability_context.get(player.id,{}) if player else {},
            'player_id': str(player.id) if player else None, 'game_id': str(game.id) if game else None,
            'position': position, 'team': info.get('team'), 'starter': pid in roster.starters,
            'injury_status': info.get('injury_status') or 'unknown',
            'identity_status': 'exact_id_match' if player else 'unresolved',
            'status': 'unsupported_position' if position not in STATS else 'unresolved_identity' if not player else 'ready' if any(f['status']=='ready' for f in forecasts) else 'insufficient_history',
            'opponent': opponent.name if opponent else None,
            'game_time': game.game_time.isoformat() if game else None, 'stats': forecasts})
    return {**base, 'status': 'experimental', 'league_id': league.league_id, 'league_name': league.name,
        'generated_at': now.isoformat(), 'roster_synced_at': roster.synced_at.isoformat(), 'players': players,
        'notes': ['Full-game conditional-on-playing estimates, not live in-game or betting advice.',
            'Roster injury labels are not verified game-day availability. No injury or opponent adjustment is applied.',
            'Historical 10th–90th ranges are descriptive, not calibrated prediction intervals.',
            'Candidate is not promoted; evaluation uses corrected history and does not prove future performance.']}
