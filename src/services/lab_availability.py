"""Reuse event-scoped source evidence; no invented participation probability."""
from pathlib import Path
from sqlalchemy import select
from config.settings import get_settings
from src.models.identity import PlayerExternalId
from src.services.injury_evidence import game_snapshots, for_game

async def contexts(db, sport, players, games, now):
    links=(await db.scalars(select(PlayerExternalId).where(PlayerExternalId.player_id.in_(players),
        PlayerExternalId.source=='espn_'+sport))).all() if players else []
    ids={}
    for link in links: ids.setdefault(link.player_id,[]).append(link.external_id)
    evidence=game_snapshots(Path(get_settings().raw_archive_dir)/'football_availability',now)
    result={}
    for pid, game in games.items():
        context=for_game({},game,ids.get(pid,[]),evidence,now).get('game_availability',{})
        result[pid]={'status':'no_scheduled_game' if game is None else 'unverified',**context,'shadow_action':'abstain' if context.get('hold_recommendation') else 'conditional_only',
            'participation_probability':None,'used_for_numeric_adjustment':False}
    return result
