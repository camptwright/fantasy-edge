"""Sport-specific margin/total regressions evaluated on subsequent days.

The features remain the current Elo margin and team scoring averages. Scale,
bias and residual variance are learned separately for each sport from earlier
games. This is a shadow candidate; no serving probability is replaced.
"""
import math
from collections import defaultdict
from dataclasses import dataclass
from sqlalchemy import select
from src.models.facts import Game
from src.services.backtest import TeamState, BacktestPrediction, _closing_lines_by_game, brier_score, log_loss
from src.services.elo import apply_result, implied_margin, update_scoring_average, spread_cover_probability
from src.services.totals import expected_total_points, is_qualified, total_over_probability
from src.services.model_review import review


@dataclass
class Regression:
    n: int = 0
    sx: float = 0
    sy: float = 0
    sxx: float = 0
    sxy: float = 0
    syy: float = 0

    def update(self, x, y):
        self.n += 1
        self.sx += x
        self.sy += y
        self.sxx += x*x
        self.sxy += x*y
        self.syy += y*y

    def parameters(self):
        if self.n < 100:
            return None
        xx = self.sxx - self.sx*self.sx/self.n
        if xx <= 1e-9:
            return None
        xy = self.sxy - self.sx*self.sy/self.n
        slope = xy / xx
        intercept = (self.sy - slope*self.sx)/self.n
        sse = self.syy - self.sy*self.sy/self.n - slope*xy
        sigma = math.sqrt(max(sse/(self.n-2), 0))
        return (slope, intercept, sigma) if sigma > 0 else None

    def predict(self, x):
        params = self.parameters()
        return None if params is None else (params[0]*x+params[1], params[2])


def above(mean, sigma, threshold):
    return 0.5 * math.erfc((threshold-mean)/(sigma*math.sqrt(2)))


def replay(games, lines, sport):
    models = {'spread': Regression(), 'total': Regression()}
    states = defaultdict(TeamState)
    days = defaultdict(list)
    rows = {m: {'candidate': [], 'baseline': []} for m in models}
    errors = {m: [] for m in models}
    for game in games:
        if game.game_time is not None and game.home_team_id and game.away_team_id:
            days[game.game_time.date()].append(game)
    for day in sorted(days):
        pending = []
        # Freeze all inputs within each day; doubleheaders cannot leak results.
        for game in days[day]:
            home, away = states[game.home_team_id], states[game.away_team_id]
            margin = game.home_score-game.away_score
            total = game.home_score+game.away_score
            features = {'spread': (implied_margin(home.rating, away.rating), margin)}
            if is_qualified(home) and is_qualified(away):
                features['total'] = (expected_total_points(home, away), total)
            for market, (x, y) in features.items():
                prediction = models[market].predict(x)
                pending.append((market, x, y))
                if prediction is None:
                    continue
                mean, sigma = prediction
                errors[market].append((mean-y)**2)
                line = lines.get(game.id, {}).get(market)
                if line is None:
                    continue
                threshold = -line if market == 'spread' else line
                if y == threshold:
                    continue
                baseline = (spread_cover_probability(home.rating, away.rating, line, sport)
                    if market == 'spread' else total_over_probability(x, line, sport))
                for kind, p in [('candidate', above(mean, sigma, threshold)), ('baseline', baseline)]:
                    rows[market][kind].append(BacktestPrediction(game.id, market, p, float(y>threshold)))
        for market, x, y in pending:
            models[market].update(x, y)
        for game in sorted(days[day], key=lambda g: (g.game_time, str(g.id))):
            h, a = states[game.home_team_id], states[game.away_team_id]
            h.rating, a.rating = apply_result(h.rating, a.rating, game.home_score, game.away_score)
            update_scoring_average(h, scored=game.home_score, allowed=game.away_score)
            update_scoring_average(a, scored=game.away_score, allowed=game.home_score)
    return {m: {
        'trained_games': models[m].n, 'parameters': models[m].parameters(),
        'point_rmse': math.sqrt(sum(errors[m])/len(errors[m])) if errors[m] else None,
        'point_samples': len(errors[m]),
        'market_scores': {kind: {'samples': len(ps), 'brier': brier_score(ps), 'log_loss': log_loss(ps)}
                          for kind, ps in rows[m].items()},
        'promotion_eligible': False,
        'promotion_review': review(rows[m]['candidate'], rows[m]['baseline']),
    } for m in models}


async def evaluate_sport_distributions(db, sport):
    games = (await db.scalars(select(Game).where(Game.sport == sport, Game.status == 'final',
        Game.home_score.isnot(None), Game.away_score.isnot(None))
        .order_by(Game.game_time.asc().nulls_last(), Game.id))).all()
    lines = await _closing_lines_by_game(db, [g.id for g in games])
    return replay(games, lines, sport)
