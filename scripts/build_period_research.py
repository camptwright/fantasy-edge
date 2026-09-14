"""Manual 2024/2025 NFL history validation and frozen-recipe evaluation.

Uses the offline nflreadpy dependency. No production facts/model writes.
RAW_ARCHIVE_DIR controls the immutable research artifact destination.
"""
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from src.ingest.nflverse import _nflreadpy
from src.scheduler.calibration import archive
from src.services.period_history import FIELDS, validate_game
from src.services.period_candidates import evaluate


def run():
    nfl = _nflreadpy()
    all_games, sources, season_reports = [], [], []
    for season in (2024, 2025):
        pbp = nfl.load_pbp([season])
        stats = nfl.load_player_stats([season])
        schedules = nfl.load_schedules([season]).to_dicts()
        columns = {'game_id', 'play_id', 'order_sequence', 'play_deleted', 'play_type_nfl',
            'play_type', 'qtr', 'quarter_seconds_remaining', 'total_home_score', 'total_away_score',
            'two_point_attempt', 'lateral_reception', 'lateral_rush', 'lateral_recovery',
            'touchdown', 'td_player_id'}
        columns.update(field for pair in FIELDS.values() for field in pair)
        raw = {'season': season, 'pbp': pbp.select(sorted(columns)).to_dicts(),
               'boxscores': stats.select(['game_id', 'player_id', 'position', *FIELDS,
                   'rushing_tds', 'receiving_tds', 'special_teams_tds', 'def_tds']).to_dicts(),
               'schedules': [{k: r[k] for k in ('game_id', 'season', 'game_type', 'gameday',
                                             'home_score', 'away_score')} for r in schedules]}
        source = archive('period-history-inputs', raw)
        sources.append({'season': season, 'archive': source,
                        'sha256': hashlib.sha256(Path(source).read_bytes()).hexdigest()})
        plays, boxes = defaultdict(list), defaultdict(list)
        for row in raw['pbp']: plays[row['game_id']].append(row)
        for row in raw['boxscores']: boxes[row['game_id']].append(row)
        games = [validate_game(plays[s['game_id']], boxes[s['game_id']], s)
                 for s in raw['schedules'] if s['game_type'] != 'PRE' and s['home_score'] is not None]
        all_games.extend(games)
        season_reports.append({'season': season, 'scheduled_final_games': len(games),
            'timeline_passes': sum(not g['blockers'] for g in games),
            'scorer_reconciled_games': sum(g.get('scorer_reconciled', False) for g in games),
            'family_reconciled_games': {s: sum(g['families'].get(s, {}).get('reconciled', False) for g in games) for s in FIELDS},
            'blockers': dict(Counter(b for g in games for b in g['blockers']))})
    dataset = archive('period-history-validated', {'sources': sources, 'games': all_games,
        'validation_level': 'same_provider_final_totals_reconciled_not_independent', 'serving_enabled': False})
    evaluation = evaluate(all_games)
    source_root = Path(__file__).resolve().parents[1]/'src/services'
    code_hashes = {name: hashlib.sha256((source_root/name).read_bytes()).hexdigest()
                   for name in ('period_history.py', 'period_candidates.py')}
    evaluation['code_hashes'] = code_hashes
    predictions = archive('period-model-evaluation', evaluation)
    summary = {'schema_version': 1, 'status': 'research', 'sport': 'nfl',
        'generated_at': datetime.now(timezone.utc).isoformat(), 'seasons': season_reports,
        'metrics': evaluation['metrics'], 'recipe': evaluation['recipe'],
        'recipe_hash': evaluation['recipe_hash'], 'limitations': evaluation['limitations'],
        'code_hashes': code_hashes,
        'evaluation_type': evaluation['evaluation_type'], 'baseline_note': evaluation['baseline_note'],
        'dataset_archive': dataset, 'evaluation_archive': predictions, 'serving_enabled': False,
        'ncaaf_status': 'not_validated',
        'promotion_blockers': ['independent_boxscore_audit', 'pregame_participation_cohort',
            'exact_product_settlement_binding', 'prospective_market_probability_evaluation']}
    path = archive('period-research-status', summary)
    print(json.dumps({'status_archive': path, 'seasons': season_reports, 'evaluated_markets': len(evaluation['metrics'])}))


if __name__ == '__main__':
    run()
