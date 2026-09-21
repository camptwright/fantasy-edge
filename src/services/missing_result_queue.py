"""Read-only work queue derived from immutable NFL player-lab forecasts.

No synthetic zeros or automatic correction approvals. Existing per-game result
retry state remains the durable execution queue; this exposes unresolved work.
"""
import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select
from config.settings import get_settings
from src.models.facts import Game, PlayerGameStat
from src.models.governance import ResultSyncState
from src.models.identity import Player
from starlette.concurrency import run_in_threadpool
from src.services.result_eligibility import no_pending_correction
from src.services.stat_identity import canonical_stat
from src.services.forecast_grading import load_cohort


def classify(game_status, player_rows, stat_present, pending):
    if game_status is None: return 'missing_game'
    if game_status in ('scheduled','in_progress'): return 'awaiting_final'
    if game_status != 'final': return 'event_status_review'
    if pending: return 'pending_correction'
    if not player_rows: return 'missing_player_results'
    if not stat_present: return 'missing_stat_category'
    return 'resolved'


def add_fantasy_records(records, forecasts):
    """Expand frozen scoring weights; deduplicate across model versions/leagues."""
    for row in forecasts:
        for stat in row.get('prediction',{}).get('scoring_weights',{}):
            key=(row['game_id'],row['player_id'],canonical_stat(stat))
            if key not in records:
                records[key]={**row,'kind':'player','stat':stat,
                    'name':row.get('name') or row['player_id'],'sources':[]}
            if 'fantasy_prospective' not in records[key]['sources']:
                records[key]['sources'].append('fantasy_prospective')
            # Keep the earliest real capture when several models need one fact.
            if datetime.fromisoformat(row['captured_at'])<datetime.fromisoformat(records[key]['captured_at']):
                records[key]['captured_at']=row['captured_at']


async def queue(db, limit=200):
    root=Path(get_settings().raw_archive_dir)
    directory=root/'nfl-player-prospective'/'forecasts'
    records={}
    for path in directory.glob('*.json'):
        row=json.loads(path.read_text())
        row={**row,'kind':'player','sources':['nfl_player_lab']}
        records.setdefault((row['game_id'],row['player_id'],canonical_stat(row['stat'])),row)
    for path in (root/'college-player-prospective'/'forecasts').glob('*.json'):
        row=json.loads(path.read_text())
        row={**row,'kind':'player','sources':['college_player_lab']}
        records.setdefault((row['game_id'],row['player_id'],canonical_stat(row['stat'])),row)
    cohort, _, _ = await run_in_threadpool(load_cohort,root/'forecasts')
    for _, ((captured,_),row) in cohort.items():
        key=(row['game_id'],row.get('player_id') or '',canonical_stat(row['market']))
        if key in records:
            if 'production' not in records[key]['sources']: records[key]['sources'].append('production')
        else:
            records[key]={**row,'name':row.get('player_name') or row.get('player_id') or 'Team market',
                'captured_at':captured.isoformat(),'sources':['production']}
    add_fantasy_records(records,(json.loads(p.read_text()) for p in
        (root/'fantasy-prospective'/'forecasts').glob('*.json')))
    ids={uuid.UUID(k[0]) for k in records}
    games={str(g.id):g for g in (await db.scalars(select(Game).where(Game.id.in_(ids)))).all()} if ids else {}
    facts=(await db.scalars(select(PlayerGameStat).where(PlayerGameStat.game_id.in_(ids)))).all() if ids else []
    safe=set((await db.scalars(select(PlayerGameStat.id).where(PlayerGameStat.game_id.in_(ids),no_pending_correction()))).all()) if ids else set()
    present={(str(r.game_id),str(r.player_id),canonical_stat(r.stat_type)) for r in facts}
    participants={(str(r.game_id),str(r.player_id)) for r in facts}
    disputed={(str(r.game_id),str(r.player_id)) for r in facts if r.id not in safe}
    states=(await db.scalars(select(ResultSyncState).where(ResultSyncState.game_id.in_(ids)))).all() if ids else []
    states={(str(r.game_id),r.provider):r for r in states}
    player_ids={uuid.UUID(k[1]) for k in records if k[1]}
    names={str(p.id):p.full_name for p in (await db.scalars(select(Player).where(Player.id.in_(player_ids)))).all()} if player_ids else {}
    items=[]
    for key,forecast in sorted(records.items()):
        game=games.get(key[0])
        sport=game.sport if game else 'unknown'
        provider={'mlb':'mlb_stats_api','nhl':'nhl_api'}.get(sport,'espn_'+sport)
        state=states.get((key[0],provider))
        reason=classify(game.status if game else None,key[:2] in participants,key in present,key[:2] in disputed)
        if game and game.status=='final' and forecast.get('kind')=='team':
            reason='missing_team_score' if game.home_score is None or game.away_score is None else 'resolved'
        if game and (game.game_time is None or datetime.fromisoformat(forecast['captured_at'])>=game.game_time):
            reason='invalid_capture_time'
        if reason in ('resolved','awaiting_final'): continue
        items.append({'game_id':key[0],'player_id':key[1],'name':names.get(key[1],forecast['name']),'stat':key[2],
            'sport':sport,'sources':forecast['sources'],'provider':provider,
            'reason':reason,'next_retry_at':state.next_attempt_at.isoformat() if state else None,
            'retry_state':state.status if state else 'untracked',
            'action':'review_capture_timing_no_result_retry' if reason=='invalid_capture_time' else 'await_provider_confirmation' if reason=='pending_correction' else 'inspect_official_boxscore_and_participation',
            'note':'Missing does not establish zero, DNP, or bookmaker void.'})
    return {'scope':'NFL and college pregame player labs, fantasy scoring forecasts, and production player/team forecasts across sports. Retrospective college reports are not included.',
        'generated_at':datetime.now(timezone.utc).isoformat(),'total':len(items),
        'counts':dict(Counter(r['reason'] for r in items)),'items':items[:limit],'truncated':len(items)>limit}
