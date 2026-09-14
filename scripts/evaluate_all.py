"""Evaluate every sport with available history; write JSON to stdout.

Read-only evaluation, suitable for external scheduling. No model promotion.
Run: python -m scripts.evaluate_all
"""
import asyncio
import json
from datetime import datetime, timezone
from sqlalchemy import select, text
from config.settings import get_settings
from src.db.client import get_worker_db
from src.models.facts import Game
from src.services.backtest import run_backtest, brier_score, log_loss, calibration_curve
from src.services.prop_backtest import run_prop_backtest
from src.services.probability_calibration import experiment
from src.services.sport_distributions import evaluate_sport_distributions


def score(rows):
    return {'samples': len(rows), 'brier': brier_score(rows), 'log_loss': log_loss(rows),
            'reliability': calibration_curve(rows), 'promotion_eligible': False,
            'candidate': experiment(rows)}


async def evaluate():
    output = {'evaluated_at': datetime.now(timezone.utc).isoformat(), 'sports': {}}
    for sport in get_settings().supported_sports:
        try:
            async with get_worker_db() as db:
                await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
                await db.execute(text("SET LOCAL statement_timeout = '120s'"))
                seasons = list((await db.scalars(select(Game.season).where(
                    Game.sport == sport, Game.status == 'final').distinct())).all())
                team = await run_backtest(db, sport, seasons)
                props, exclusions = await run_prop_backtest(db, sport)
                output['sports'][sport] = {
                    'seasons': sorted(seasons),
                    'team_markets': {m: score([p for p in team if p.market == m])
                                     for m in ('moneyline', 'spread', 'total')},
                    'player_props': {stat: score(rows) for stat, rows in props.items()},
                    'prop_exclusions': exclusions,
                    'sport_distributions': await evaluate_sport_distributions(db, sport),
                    'note': 'Unlinked props cannot be graded. Missing prop families are not calibrated.',
                }

            output['sports'][sport]['status'] = 'complete'
        except Exception as exc:
            output['sports'][sport] = {'status': 'failed', 'error_type': type(exc).__name__}
    output['status'] = 'complete' if all(r['status'] == 'complete' for r in output['sports'].values()) else 'partial'
    output['completed_at'] = datetime.now(timezone.utc).isoformat()
    from src.services.model_version import manifest
    output['serving_version_manifest'] = manifest()
    return output


if __name__ == '__main__':
    print(json.dumps(asyncio.run(evaluate()), indent=2))
