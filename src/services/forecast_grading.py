"""Prospective baseline scorecard. Never refit or reconstruct probabilities.

One earliest forecast per model/event/market/player; line/book/side are NOT
extra samples. Full archives remain available for future policy comparisons.
Regrade from current facts each run so delayed results/corrections are included.
"""
import json
import math
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, text
from src.models.facts import Game, PlayerGameStat
from src.models.governance import ResultCorrection
from src.services.stat_identity import canonical_stat, canonical_results
from src.services.prospective_review import scorecard


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('timezone required')
    return parsed


def outcome(record, game, stats, captured_at, disputed=None):
    if game is None:
        return 'missing_game', None
    if game.game_time is None or captured_at >= game.game_time:
        return 'invalid_timing', None
    if game.status != 'final':
        return ('pending' if game.status in ('scheduled', 'in_progress') else 'needs_review'), None
    market, side = record['market'], record.get('side')
    if record['kind'] == 'player':
        stat_key = (record['player_id'], record['game_id'], canonical_stat(market))
        if disputed and stat_key in disputed:
            return 'needs_review', None
        value = stats.get(stat_key)
        if value is None:
            return 'missing_result', None
        margin = value - float(record['line'])
    else:
        if game.home_score is None or game.away_score is None:
            return 'missing_result', None
        margin = game.home_score - game.away_score
        if market in ('moneyline', 'spread') and side in ('home', 'away'):
            margin *= 1 if side == 'home' else -1
            if market == 'spread':
                margin += float(record['line'])
        elif market == 'total' and side in ('over', 'under'):
            margin = (game.home_score + game.away_score - float(record['line'])) * (1 if side == 'over' else -1)
        else:
            return 'unsupported', None
    if not math.isfinite(margin):
        return 'invalid', None
    return ('push', None) if margin == 0 else ('graded', int(margin > 0))


def load_cohort(directory, include_shadows=False):
    selected, raw, files, shadows = {}, 0, 0, {}
    for path in sorted(Path(directory).glob('*.json')):
        # Fail closed on a corrupt archive: never publish partial coverage.
        payload = json.loads(path.read_text())
        if payload['schema_version'] != 1:
            raise ValueError('unsupported forecast schema')
        captured = timestamp(payload['captured_at'])
        version = payload.get('cohort_version', payload['model_version'])
        files += 1
        for record in payload['records']:
            raw += 1
            uuid.UUID(record['game_id'])
            if record['kind'] not in ('player', 'team'):
                raise ValueError('unknown forecast kind')
            key = (version, record['game_id'], record['kind'], canonical_stat(record['market']), record.get('player_id'))
            # Quote UUID is an outcome-independent, deterministic tie breaker.
            rank = (captured, record['quote_id'])
            if key not in selected or rank < selected[key][0]:
                selected[key] = (rank, record)
            if include_shadows:
                for recipe, shadow in record.get('shadow_predictions', {}).items():
                    if shadow.get('model_probability') is None:
                        continue
                    shadow_key = (*key, recipe+':'+shadow.get('recipe_version', 'unversioned'))
                    if shadow_key not in shadows or rank < shadows[shadow_key][0]:
                        shadows[shadow_key] = (rank, record, shadow)
    return (selected, raw, files, shadows) if include_shadows else (selected, raw, files)


def unresolved_evidence(records, games, stats):
    """One diagnostic per outcome, not per quote or serving model version.

    Absence is not a zero, DNP, or bookmaker void. This report only describes
    which recorded evidence is missing, without changing grading decisions.
    """
    by_player, game_counts = {}, Counter()
    for player, game, stat in stats:
        by_player.setdefault((player, game), set()).add(stat)
        game_counts[game] += 1
    unique = {}
    for record in records:
        gid, pid = record['game_id'], record.get('player_id')
        market = canonical_stat(record['market'])
        game = games.get(gid)
        available = sorted(by_player.get((pid, gid), set()))
        if record['kind'] != 'player':
            reason = 'missing_team_score'
        elif not game_counts[gid]:
            reason = 'no_game_player_results'
        elif not available:
            reason = 'no_player_results'
        else:
            reason = 'missing_stat_with_other_player_results'
        key = (gid, pid, record['kind'], market)
        unique[key] = {'sport': game.sport if game else 'unknown', 'game_id': gid,
            'player_id': pid, 'kind': record['kind'], 'market': market,
            'reason': reason, 'available_player_stats': available,
            'espn_event_id': getattr(game, 'espn_event_id', None),
            'mlb_game_pk': getattr(game, 'mlb_game_pk', None)}
    rows = sorted(unique.values(), key=lambda r: (r['sport'], r['game_id'], r['player_id'] or '', r['market']))
    return {'unique_outcomes': len(rows), 'counts': dict(Counter(r['reason'] for r in rows)),
            'items': rows[:200], 'truncated': len(rows) > 200,
            'note': 'Missing evidence is not proof of zero, non-participation, or a void. '
                    'Diagnostics do not alter outcomes or promotion gates.'}


async def grade(db, directory):
    cohort, raw, files, shadow_cohort = load_cohort(directory, include_shadows=True)
    await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
    ids = sorted({key[1] for key in cohort})
    games, stats, disputed = {}, {}, set()
    for start in range(0, len(ids), 1000):
        batch = [uuid.UUID(value) for value in ids[start:start+1000]]
        games.update({str(g.id): g for g in (await db.scalars(select(Game).where(Game.id.in_(batch)))).all()})
        facts = (await db.scalars(select(PlayerGameStat).where(PlayerGameStat.game_id.in_(batch)))).all()
        stats.update({(str(p), str(g), s): value for (p, g, s), value in canonical_results(facts).items()})
        pending = (await db.scalars(select(PlayerGameStat).join(ResultCorrection,
            ResultCorrection.stat_id == PlayerGameStat.id).where(
                PlayerGameStat.game_id.in_(batch), ResultCorrection.status == 'pending'))).all()
        disputed.update((str(f.player_id), str(f.game_id), canonical_stat(f.stat_type)) for f in pending)
    groups, counts, shadow_groups, unresolved = {}, Counter(), {}, []
    for key, ((captured, _), record) in cohort.items():
        game = games.get(record['game_id'])
        sport = game.sport if game else record['prediction'].get('sport', 'unknown')
        group_key = (sport, record['kind'], canonical_stat(record['market']), key[0])
        group = groups.setdefault(group_key, {'counts': Counter(), 'scores': [], 'baseline_scores': [], 'games': set(), 'evaluation': []})
        try:
            p = float(record['prediction']['model_probability'])
            if not math.isfinite(p) or not 0 <= p <= 1:
                raise ValueError('invalid probability')
            status, result = outcome(record, game, stats, captured, disputed)
        except (TypeError, ValueError, KeyError):
            status, result = 'invalid', None
        counts[status] += 1
        if status == 'missing_result':
            unresolved.append(record)
        group['counts'][status] += 1
        prediction = record['prediction']
        evaluation = {'captured_at': captured, 'game_id': record['game_id'],
            'market_key': canonical_stat(record['market'])+':'+str(record.get('player_id', 'team')),
            'probability': prediction.get('model_probability'), 'baseline': prediction.get('baseline_model_probability'),
            'market_probability': prediction.get('market_fair_probability', prediction.get('fair_probability')),
            'outcome': result, 'status': status, 'protocol_verified': prediction.get('actionable') is True}
        group['evaluation'].append(evaluation)
        if result is not None:
            group['scores'].append((p, result))
            group['games'].add(record['game_id'])
            baseline = record['prediction'].get('baseline_model_probability')
            if isinstance(baseline, (int, float)) and math.isfinite(baseline) and 0 <= baseline <= 1:
                group['baseline_scores'].append((baseline, result))
    # A new recipe may first appear AFTER a game's first baseline capture.
    # Give each recipe its own outcome-independent earliest-capture cohort.
    for key, ((captured, _), record, shadow) in shadow_cohort.items():
        game = games.get(record['game_id'])
        prediction = record['prediction']
        sport = game.sport if game else prediction.get('sport', 'unknown')
        group_key = (sport, record['kind'], canonical_stat(record['market']), key[0], key[-1])
        try:
            p = float(shadow['model_probability'])
            if not math.isfinite(p) or not 0 <= p <= 1:
                raise ValueError('invalid shadow probability')
            state, result = outcome(record, game, stats, captured, disputed)
        except (TypeError, ValueError, KeyError):
            state, result = 'invalid', None
        shadow_groups.setdefault(group_key, []).append({'captured_at': captured, 'game_id': record['game_id'],
            'market_key': canonical_stat(record['market'])+':'+str(record.get('player_id', 'team')),
            'probability': shadow['model_probability'],
            'baseline': prediction.get('baseline_model_probability') if shadow.get('comparison_baseline') == 'retained_baseline'
                else prediction.get('model_probability'),
            'market_probability': prediction.get('market_fair_probability', prediction.get('fair_probability')),
            'outcome': result, 'status': state, 'protocol_verified': prediction.get('actionable') is True})
    reports = []
    for (sport, kind, market, version), group in sorted(groups.items()):
        scores = group['scores']
        n = len(scores)
        baseline_scores = group['baseline_scores']
        bn = len(baseline_scores)
        reports.append({'sport': sport, 'kind': kind, 'market': market, 'model_version': version,
            'counts': dict(group['counts']), 'sample_size': n, 'independent_games': len(group['games']),
            'paired_baseline_samples': bn,
            'paired_baseline_brier': sum((p-y)**2 for p, y in baseline_scores)/bn if bn else None,
            'paired_baseline_log_loss': sum(-math.log(max(1e-15, p if y else 1-p)) for p, y in baseline_scores)/bn if bn else None,
            'brier_score': sum((p-y)**2 for p, y in scores)/n if n else None,
            'log_loss': sum(-math.log(max(1e-15, p if y else 1-p)) for p, y in scores)/n if n else None})
        reports[-1]['prospective_scorecard'] = scorecard(group['evaluation'])
    return {'schema_version': 1, 'status': 'available' if files else 'awaiting_forecasts',
        'graded_at': datetime.now(timezone.utc).isoformat(), 'archive_files': files,
        'raw_records': raw, 'cohort_records': len(cohort), 'duplicates_excluded': raw-len(cohort),
        'counts': dict(counts), 'reports': reports,
        'pending_correction_outcomes': len(disputed),
        'unresolved_evidence': unresolved_evidence(unresolved, games, stats),
        'shadow_reports': [{'sport': sport, 'kind': kind, 'market': market, 'model_version': version,
            'recipe': recipe, 'status': 'shadow_only', 'scorecard': scorecard(rows)}
            for (sport, kind, market, version, recipe), rows in sorted(shadow_groups.items())],
        'latest_selected_capture_at': max((v[0][0] for v in cohort.values()), default=None).isoformat() if cohort else None,
        'note': 'Earliest captured forecast per model/event/market/player; one book, line and side. Player probabilities score OVER. Pushes and missing results are excluded. Props within a game are correlated. Statistical outcomes, not bookmaker settlement or profit. No automatic model promotion.'}


def latest_report(directory):
    paths = sorted(Path(directory).glob('*.json'))
    if not paths:
        return {'status': 'awaiting_grading', 'reports': []}
    try:
        report = json.loads(paths[-1].read_text())
        report['stale'] = (datetime.now(timezone.utc)-timestamp(report['graded_at'])).total_seconds() > 7200
        return report
    except (OSError, ValueError, KeyError):
        return {'status': 'unavailable', 'reports': []}
