"""Read-only archive/identity diagnostics. Never infer zeros or repair forecasts."""
import asyncio
import json
from collections import Counter
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.facts import Game
from src.models.identity import Player, PlayerExternalId


def classify(record, game, player, external_ids, observation):
    team = ('unknown' if player.current_team_id is None else
            'current_team_matches' if player.current_team_id in
            (game.home_team_id, game.away_team_id) else 'current_team_differs')
    result = {'player_id': record['player_id'], 'game_id': record['game_id'],
              'name': record['name'], 'current_team_check': team}
    if not external_ids:
        return {**result, 'evidence': 'missing_provider_identity'}
    if len(external_ids) != 1:
        return {**result, 'evidence': 'ambiguous_provider_identity'}
    if not observation:
        return {**result, 'evidence': 'missing_archive'}
    payload = observation.get('payload', {})
    competitions = payload.get('header', {}).get('competitions', [])
    if (observation.get('provider') != 'espn_nfl' or
        observation.get('game_id') != str(game.id) or
        str(observation.get('event_id')) != str(game.espn_event_id) or
        not any(str(c.get('id')) == str(game.espn_event_id) and
                c.get('status', {}).get('type', {}).get('completed') is True
                for c in competitions)):
        return {**result, 'evidence': 'unverified_archive_binding'}
    rows = [a for t in payload.get('boxscore', {}).get('players', [])
            for s in t.get('statistics', []) for a in s.get('athletes', [])
            if str(a.get('athlete', {}).get('id')) in external_ids]
    evidence = ('athlete_absent_from_boxscore' if not rows else
                'explicit_dnp_rows_only' if all(a.get('didNotPlay') is True for a in rows)
                else 'athlete_present_requires_stat_review')
    return {**result, 'evidence': evidence,
            'observed_at': observation.get('observed_at'),
            'payload_hash': observation.get('payload_hash')}


async def execute():
    root = Path(get_settings().raw_archive_dir)
    reports = sorted((root/'fantasy-prospective'/'reports').glob('*.json'))
    if not reports:
        return {'status': 'missing_report'}
    report = json.loads(reports[-1].read_text())
    records = [json.loads((root/'fantasy-prospective'/'forecasts'/
                          (g['id']+'.json')).read_text()) for g in report['grades']
               if g['status'] == 'missing_scoring_results']
    pairs = {(r['player_id'], r['game_id']): r for r in records}
    needed = {gid for _, gid in pairs}
    observations = {}
    for path in sorted((root/'result-observations').glob('*.json'), reverse=True):
        observation = json.loads(path.read_text())
        gid = observation.get('game_id')
        if gid in needed and observation.get('provider') == 'espn_nfl':
            observations.setdefault(gid, observation)
        if needed <= observations.keys():
            break
    rows = []
    async with get_worker_db() as db:
        for (pid, gid), record in sorted(pairs.items()):
            player = await db.get(Player, UUID(pid))
            game = await db.get(Game, UUID(gid))
            ids = set((await db.scalars(select(PlayerExternalId.external_id).where(
                PlayerExternalId.player_id == UUID(pid),
                PlayerExternalId.source == 'espn_nfl'))).all())
            if player is None or game is None:
                rows.append({'player_id': pid, 'game_id': gid, 'evidence': 'missing_entity'})
            else:
                rows.append(classify(record, game, player, ids, observations.get(gid)))
    return {'status': 'diagnostic_only', 'report': reports[-1].name,
            'counts': dict(Counter(r['evidence'] for r in rows)), 'rows': rows,
            'scope': 'Current teams are not historical roster evidence. Boxscore absence is not DNP or zero. No records modified.'}


if __name__ == '__main__':
    print(json.dumps(asyncio.run(execute())))
