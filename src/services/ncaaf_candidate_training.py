"""Fit frozen experimental distributions from prior-day replay features.

Historical boxscores lack publication timestamps. This is a provisional
distribution holdout, NOT an actual-quote probability/ROI backtest.
"""
import asyncio
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select, text
from src.db.client import get_worker_db
from src.models.facts import Game, PlayerGameStat
from src.services.backtest import TeamState
from src.services.elo import apply_result, implied_margin
from src.services.sport_distributions import Regression

STATS = {'passing_yards', 'passing_completions', 'passing_attempts', 'passing_touchdowns',
         'passing_interceptions', 'rushing_yards', 'rushing_attempts', 'rushing_touchdowns',
         'longest_rush', 'receiving_yards', 'receptions', 'receiving_touchdowns', 'longest_reception',
         'pass_rush_yards', 'rush_rec_yards', 'rush_rec_tds', 'fg_made', 'xp_made', 'kicking_points'}
KICKING_STATS = {'fg_made', 'xp_made', 'kicking_points'}


def metrics(rows, predict):
    losses, errors = [], []
    for row in rows:
        mean, sigma = predict(row)
        error = row['value']-mean
        errors.append(error*error)
        losses.append(math.log(sigma)+0.5*(error/sigma)**2+0.5*math.log(2*math.pi))
    return {'samples': len(rows), 'independent_games': len({r['game_id'] for r in rows}),
            'rmse': math.sqrt(statistics.fmean(errors)), 'gaussian_nll': statistics.fmean(losses)}


def fit(rows, kind):
    days = sorted({r['day'] for r in rows})
    if len(days) < 10:
        return {'status': 'insufficient_history', 'deployable_experimental': False,
                'replay_samples': len(rows), 'feature_days': len(days),
                'minimums': {'feature_days': 10, 'fit_samples': 100,
                             'holdout_samples': 50, 'holdout_games': 20}}
    # Reserve roughly 30% of samples, not dates: bowl-week single-game days
    # otherwise crowd out full regular-season Saturdays in the holdout.
    # The split uses counts/timestamps only, never result values.
    counts = defaultdict(int)
    for row in rows:
        counts[row['day']] += 1
    cumulative = 0
    cutoff = days[-1]
    for day in days:
        cumulative += counts[day]
        if cumulative >= int(len(rows)*.7):
            cutoff = day
            break
    train = [r for r in rows if r['day'] < cutoff]
    test = [r for r in rows if r['day'] >= cutoff]
    if len(train) < 100 or len(test) < 50 or len({r['game_id'] for r in test}) < 20:
        return {'status': 'insufficient_history', 'deployable_experimental': False,
                'fit_samples': len(train), 'holdout_samples': len(test),
                'holdout_games': len({r['game_id'] for r in test}),
                'minimums': {'fit_samples': 100, 'holdout_samples': 50, 'holdout_games': 20}}
    if kind == 'spread':
        model = Regression()
        for row in train:
            model.update(row['mean'], row['value'])
        params = model.parameters()
        if params is None:
            return {'status': 'degenerate_fit', 'deployable_experimental': False}
        slope, intercept, sigma = params
        parameters = {'slope': slope, 'intercept': intercept, 'sigma': sigma}
        def predict(r):
            return slope*r['mean']+intercept, sigma
    else:
        residuals = [(r['value']-r['mean'])/r['sigma'] for r in train]
        # Kicking's small count histories make mean shifts fragile. Preserve
        # the player's observed average and fit uncertainty only. This policy
        # is fixed by market family, never selected using holdout outcomes.
        bias = 0.0 if kind == 'player_scale_only' else max(-.5, min(.5, statistics.fmean(residuals)))
        scale = max(.5, min(3.0, math.sqrt(statistics.fmean((r-bias)**2 for r in residuals))))
        parameters = {'bias_stddev': bias, 'scale_stddev': scale}
        def predict(r):
            return r['mean']+bias*r['sigma'], scale*r['sigma']
    baseline = metrics(test, lambda r: (r['mean'], r['sigma']))
    candidate = metrics(test, predict)
    improved = candidate['gaussian_nll'] < baseline['gaussian_nll'] and candidate['rmse'] <= baseline['rmse']
    return {'status': 'experimental_holdout', 'parameters': parameters,
            'fit_policy': kind,
            'fit_samples': len(train), 'fit_through': max(r['day'] for r in train),
            'holdout_from': cutoff, 'holdout_through': max(r['day'] for r in test),
            'baseline': baseline, 'candidate': candidate, 'deployable_experimental': improved,
            'validation_passed': False,
            'note': 'Selected only when holdout distribution loss improves without worse RMSE; not betting calibration approval.'}


def replay(games, stats):
    days = defaultdict(list)
    for game in games:
        if game.game_time and game.home_team_id and game.away_team_id:
            days[game.game_time.astimezone(timezone.utc).date().isoformat()].append(game)
    by_game = defaultdict(list)
    # Explicit canonical names only: legacy ints_thrown must not duplicate
    # passing_interceptions in either history or test samples.
    for stat in stats:
        if stat.stat_type in STATS and math.isfinite(stat.value):
            by_game[stat.game_id].append(stat)
    history, states = defaultdict(list), defaultdict(TeamState)
    spread, props = [], defaultdict(list)
    for day in sorted(days):
        for game in days[day]:
            h, a = states[game.home_team_id], states[game.away_team_id]
            spread.append({'day': day, 'game_id': str(game.id), 'mean': implied_margin(h.rating, a.rating),
                           'sigma': 17.0, 'value': game.home_score-game.away_score})
            for stat in by_game[game.id]:
                values = history[(stat.player_id, stat.stat_type)]
                if len(values) < 4:
                    continue
                sigma = statistics.pstdev(values)
                if sigma <= 0:
                    continue
                props[stat.stat_type].append({'day': day, 'game_id': str(game.id),
                    'mean': statistics.fmean(values), 'sigma': sigma, 'value': stat.value})
        # Nothing from this UTC day enters another game's features today.
        for game in sorted(days[day], key=lambda g: (g.game_time, str(g.id))):
            h, a = states[game.home_team_id], states[game.away_team_id]
            h.rating, a.rating = apply_result(h.rating, a.rating, game.home_score, game.away_score)
            for stat in by_game[game.id]:
                history[(stat.player_id, stat.stat_type)].append(stat.value)
    return spread, props


async def train(db):
    await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
    games = (await db.scalars(select(Game).where(Game.sport == 'ncaaf', Game.status == 'final',
        Game.home_score.isnot(None), Game.away_score.isnot(None)).order_by(Game.game_time, Game.id))).all()
    stats = (await db.scalars(select(PlayerGameStat).join(Game, PlayerGameStat.game_id == Game.id)
        .where(Game.sport == 'ncaaf', Game.status == 'final'))).all()
    spread, props = replay(games, stats)
    return {'schema_version': 1, 'candidate_id': 'ncaaf-distributions-v3-research',
        'split_policy': 'earliest ~70% samples fit; boundary UTC day entirely held out; no outcome-based split',
        'created_at': datetime.now(timezone.utc).isoformat(), 'sport': 'ncaaf',
        'approval': 'User authorized experimental spread/player-prop deployment with baselines retained.',
        'validation_passed': False, 'spread': fit(spread, 'spread'),
        'player_props': {stat: fit(props.get(stat, []),
            'player_scale_only' if stat in KICKING_STATS else 'player') for stat in sorted(STATS)},
        'limitations': ['No actual-quote holdout for props; distribution loss is not Brier/ROI.',
            'Historical publication timestamps unavailable; prior-day cutoff is provisional.',
            'No bookmaker-specific settlement, injury/news features, or automatic parameter replacement.',
            'Holdout reused for deployment selection; future prospective evidence is required.']}


async def main():
    async with get_worker_db() as db:
        print(json.dumps(await train(db), indent=2, allow_nan=False))


if __name__ == '__main__':
    asyncio.run(main())
