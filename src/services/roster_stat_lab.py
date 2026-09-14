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
    ids_file = Path(__file__).resolve().parents[2]/'config/nfl_player_lab_ids.json'
    ids = json.loads(ids_file.read_text()).get('identities', {}) if ids_file.exists() else {}
    roster_ids = list(dict.fromkeys(str(p) for p in roster.players))[:40]
    source_ids = {pid: ({'espn_id': pid} if league.platform == 'espn' else ids.get(pid, {})) for pid in roster_ids}
    gsis = {v['gsis_id'] for v in source_ids.values() if v.get('gsis_id')}
    espn = {v['espn_id'] for v in source_ids.values() if v.get('espn_id')}
    direct = (await db.scalars(select(Player).where(Player.sport == 'nfl', Player.gsis_id.in_(gsis)))).all()
    external = (await db.execute(select(PlayerExternalId.external_id, Player).join(Player, Player.id == PlayerExternalId.player_id)
        .where(Player.sport == 'nfl', PlayerExternalId.source == 'espn_nfl', PlayerExternalId.external_id.in_(espn)))).all()
    by_gsis = {p.gsis_id: p for p in direct}
    by_espn = {key: p for key, p in external}
    resolved = {}
    for pid, identity in source_ids.items():
        matches = [p for p in (by_gsis.get(identity.get('gsis_id')), by_espn.get(identity.get('espn_id'))) if p]
        if matches and len({p.id for p in matches}) == 1:
            resolved[pid] = matches[0]
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
    for pid in roster_ids:
        info, player = catalog.get(pid, {}), resolved.get(pid)
        position = info.get('position')
        team = team_by_abbr.get(aliases.get(info.get('team'), info.get('team')))
        game = next((g for g in games if team and team.id in (g.home_team_id, g.away_team_id)), None)
        opponent = team_by_id.get(game.away_team_id if game.home_team_id == team.id else game.home_team_id) if game else None
        forecasts = [forecast(list(histories[player.id].values()), s, now) for s in STATS.get(position, [])] if player else []
        players.append({'roster_player_id': pid, 'name': ' '.join(str(info.get(k) or '') for k in ('first_name', 'last_name')).strip() or pid,
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
