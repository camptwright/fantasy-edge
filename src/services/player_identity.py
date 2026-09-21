"""Shared exact NFL platform identity resolution. Never match display names."""
import json
from pathlib import Path
from sqlalchemy import select
from src.models.identity import Player, PlayerExternalId


async def resolve_external_players(db, sport, source, player_ids):
    """Provider IDs are always scoped by both sport and provider."""
    if (sport,source) not in {('nfl','espn_nfl'),('ncaaf','espn_ncaaf')}:
        raise ValueError('Unsupported identity namespace')
    rows = (await db.execute(select(PlayerExternalId.external_id,Player).join(Player,Player.id==PlayerExternalId.player_id)
        .where(Player.sport==sport,PlayerExternalId.source==source,
               PlayerExternalId.external_id.in_([str(p).strip() for p in player_ids])))).all()
    return dict(rows)


async def resolve_platform_players(db, platform, player_ids):
    path = Path(__file__).resolve().parents[2]/'config/nfl_player_lab_ids.json'
    catalog = json.loads(path.read_text()).get('identities', {}) if path.exists() else {}
    identities = {str(pid): ({'espn_id':str(pid)} if platform=='espn' else catalog.get(str(pid), {}) if platform=='sleeper' else {}) for pid in player_ids}
    gsis = {str(v['gsis_id']).strip() for v in identities.values() if v.get('gsis_id')}
    espn = {str(v['espn_id']).strip() for v in identities.values() if v.get('espn_id')}
    direct = (await db.scalars(select(Player).where(Player.sport=='nfl',Player.gsis_id.in_(gsis)))).all()
    external = await resolve_external_players(db,'nfl','espn_nfl',espn)
    by_gsis = {p.gsis_id:p for p in direct}
    by_espn = dict(external)
    resolved = {}
    for pid, identity in identities.items():
        matches = [p for p in (by_gsis.get(str(identity.get('gsis_id','')).strip()),by_espn.get(str(identity.get('espn_id','')).strip())) if p]
        if matches and len({p.id for p in matches})==1: resolved[pid]=matches[0]
    return resolved
