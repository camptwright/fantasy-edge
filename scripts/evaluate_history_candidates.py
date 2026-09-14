"""Research-only paired audit of repaired history, season and observed workload.

Never call this prospective: result ingestion/publication times are unavailable.
All baseline probabilities and lines come from immutable original captures.
"""
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
from sqlalchemy import select, text
from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.facts import Game, PlayerGameStat
from src.models.governance import ResultCorrection
from src.services.forecast_grading import timestamp, outcome
from src.services.stat_identity import canonical_results, canonical_stat, ALIASES
from src.services.history_candidates import candidates, OPPORTUNITY
from scripts.evaluate_prop_candidates import summarize, valid


def select_history_records(directory):
    """Keep only evaluation fields, not every full feature/quote/cohort payload."""
    selected = {}
    for path in sorted(Path(directory).glob('*.json')):
        payload = json.loads(path.read_text())
        if payload['schema_version'] != 1:
            raise ValueError('unsupported forecast schema')
        captured = timestamp(payload['captured_at'])
        for record in payload['records']:
            if record['kind'] != 'player' or not valid(record['prediction'].get('baseline_model_probability')):
                continue
            key = (record['game_id'], record['player_id'], canonical_stat(record['market']))
            rank = (captured, record['quote_id'])
            if key not in selected or rank < selected[key][0]:
                compact = {k: record[k] for k in ('kind', 'game_id', 'player_id', 'market', 'line', 'quote_id')}
                compact['prediction'] = {'baseline_model_probability': record['prediction']['baseline_model_probability']}
                selected[key] = (rank, compact)
    return selected


async def evaluate():
    selected = select_history_records(Path(get_settings().raw_archive_dir)/'forecasts')
    games, histories, outcomes, disputed = {}, defaultdict(list), {}, set()
    async with get_worker_db() as db:
        await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        await db.execute(text("SET LOCAL statement_timeout='60s'"))
        games = {str(g.id): g for g in (await db.scalars(select(Game).where(
            Game.id.in_([uuid.UUID(k[0]) for k in selected])))).all()}
        # Pending NFL slates do not need their entire histories loaded to report pending.
        eligible = {key for key in selected if key[0] in games and games[key[0]].status == 'final'}
        ids = sorted({uuid.UUID(k[1]) for k in eligible})
        target_games = {k[0] for k in eligible}
        needed = {k[2] for k in eligible} | set(OPPORTUNITY.values()) | {'pitching_games_started'}
        needed |= {alias for alias, canonical in ALIASES.items() if canonical in needed}
        for offset in range(0, len(ids), 20):
            rows = (await db.execute(select(PlayerGameStat, Game).join(Game, Game.id == PlayerGameStat.game_id)
                .where(PlayerGameStat.player_id.in_(ids[offset:offset+20]), Game.status == 'final',
                       PlayerGameStat.stat_type.in_(needed)))).all()
            pending = (await db.scalars(select(PlayerGameStat).join(ResultCorrection, ResultCorrection.stat_id == PlayerGameStat.id)
                .where(PlayerGameStat.player_id.in_(ids[offset:offset+20]), ResultCorrection.status == 'pending'))).all()
            disputed.update((str(r.player_id), str(r.game_id), canonical_stat(r.stat_type)) for r in pending)
            events = {g.id: g for _, g in rows}
            per_game = defaultdict(dict)
            for (p, g, s), value in canonical_results([f for f, _ in rows]).items():
                key = (str(p), str(g), s)
                if str(g) in target_games:
                    outcomes[key] = value
                if key not in disputed:
                    per_game[(str(p), g)][s] = value
            for (p, gid), values in per_game.items():
                g = events[gid]
                if g.game_time is not None:
                    histories[p].append({'game_id': str(gid), 'time': g.game_time,
                        'season': g.season, 'game_type': g.game_type, 'values': values})
    groups, controls, statuses, reasons = defaultdict(list), defaultdict(list), Counter(), Counter()
    for (gid, pid, stat), ((captured, _), record) in selected.items():
        game = games.get(gid)
        if game and game.game_type == 'PRE':
            statuses[(game.sport, 'preseason_excluded')] += 1
            continue
        status, y = outcome(record, game, outcomes, captured, disputed)
        statuses[(game.sport if game else 'unknown', status)] += 1
        if status != 'graded':
            continue
        predictions, reason = candidates(histories[pid], stat, game.season, captured, float(record['line']))
        reasons[(game.sport, reason)] += 1
        for recipe, probability in predictions.items():
            row = {'game_id': gid, 'candidate': probability, 'outcome': y,
                   'baseline': record['prediction']['baseline_model_probability']}
            groups[(game.sport, stat, recipe)].append(row)
            if recipe != 'repaired_history_control_v1':
                controls[(game.sport, stat, recipe)].append({**row, 'baseline': predictions['repaired_history_control_v1']})
    totals = defaultdict(list)
    for (sport, _, recipe), rows in groups.items():
        totals[(sport, recipe)].extend(rows)
    def control_summary(rows):
        report = summarize(rows)
        if 'retained_baseline' in report:
            report['same_history_control'] = report.pop('retained_baseline')
        return report
    return {'evaluated_at': datetime.now(timezone.utc).isoformat(), 'status': 'retrospective_research_only',
        'recipe_sha256': hashlib.sha256(Path(__file__).resolve().parents[1].joinpath('src/services/history_candidates.py').read_bytes()).hexdigest(),
        'outcomes': [{'sport': s, 'status': t, 'count': n} for (s,t),n in sorted(statuses.items())],
        'eligibility': [{'sport': s, 'reason': r, 'count': n} for (s,r),n in sorted(reasons.items())],
        'versus_retained_baseline': [{'sport': s, 'market': m, 'recipe': r, **summarize(v)} for (s,m,r),v in sorted(groups.items())],
        'versus_same_history_control': [{'sport': s, 'market': m, 'recipe': r, **control_summary(v)} for (s,m,r),v in sorted(controls.items())],
        'sport_summaries': [{'sport': s, 'recipe': r, **summarize(v)} for (s,r),v in sorted(totals.items())],
        'limitations': ['Historical result publication/ingestion times are unavailable; repaired data may not have been available at capture.',
            'Only game times before original capture enter reconstructed features. Pending corrections excluded.',
            'Workload and pitcher role are observed past usage, not a confirmed future lineup.',
            'Earliest archived player/game/canonical-stat capture; pushes and missing outcomes excluded.',
            'Retention comparison includes data expansion; same-history control isolates mean-recipe differences.',
            'Normal-distribution sigma is held constant between research recipes; game-cluster intervals are unadjusted for multiple testing.'],
        'promotion_eligible': False, 'serving_parameters_changed': False}


if __name__ == '__main__':
    from src.scheduler.calibration import archive
    report = asyncio.run(evaluate())
    print(json.dumps({'archive': archive('history-candidate-evaluation', report), **report}, indent=2))
