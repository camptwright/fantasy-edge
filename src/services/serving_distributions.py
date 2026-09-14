"""Pinned distribution overrides; absent/invalid evidence falls back to baseline."""
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

from config.settings import get_settings

ARTIFACT_PATH = Path(__file__).resolve().parents[2]/'config/ncaaf_experimental_distributions.json'
CANDIDATE_ID = 'ncaaf-distributions-20260905-v3'


def enabled(row):
    # Manual approval is distinct from passing the historical screen. Both
    # paths still validate every parameter and remain experimental.
    return row.get('deployable_experimental') is True or row.get('user_override_approved') is True


@lru_cache(maxsize=1)
def artifact():
    try:
        data = ARTIFACT_PATH.read_bytes()
        report = json.loads(data)
        if report['schema_version'] != 1 or report['candidate_id'] != CANDIDATE_ID or report['sport'] != 'ncaaf':
            raise ValueError('unexpected artifact')
        for name, row in [('spread', report['spread']), *report['player_props'].items()]:
            if not enabled(row):
                continue
            p = row['parameters']
            if not all(math.isfinite(v) for v in p.values()):
                raise ValueError('nonfinite parameter')
            if name == 'spread':
                valid = 0 < p['slope'] < 10 and abs(p['intercept']) < 100 and 1 < p['sigma'] < 100
            else:
                valid = abs(p['bias_stddev']) <= .5 and .5 <= p['scale_stddev'] <= 3
            if not valid:
                raise ValueError('parameter outside supported bounds')
        return report, hashlib.sha256(data).hexdigest()
    except (OSError, KeyError, ValueError, TypeError, AttributeError):
        return None, None


def distribution_status():
    report, digest = artifact()
    settings = get_settings()
    spread = bool(report and settings.ncaaf_spread_calibration_enabled and enabled(report['spread']))
    props = sorted(k for k, r in report['player_props'].items() if enabled(r)) if report and settings.ncaaf_prop_calibration_enabled else []
    return {'candidate_id': CANDIDATE_ID, 'artifact_sha256': digest,
        'status': 'experimental_user_override' if spread or props else 'baseline',
        'artifact_available': report is not None, 'spread_enabled': spread, 'player_prop_stats': props,
        'manual_override_stats': [k for k in props if report['player_props'][k].get('user_override_approved') is True
                                  and report['player_props'][k].get('deployable_experimental') is not True],
        'baseline_retained': True, 'validation_passed': False,
        'evidence': report, 'scope': 'Known, pregame NCAAF events only. Totals and other sports unchanged.',
        'rollback': 'Set NCAAF_SPREAD_CALIBRATION_ENABLED=false and NCAAF_PROP_CALIBRATION_ENABLED=false; recreate api, worker, beat.'}


def spread_probability(mean_margin, home_line, baseline, sport, pregame):
    report, _ = artifact()
    if sport != 'ncaaf' or not pregame or not distribution_status()['spread_enabled']:
        return baseline, None
    p = report['spread']['parameters']
    mean = p['slope']*mean_margin+p['intercept']
    probability = .5*math.erfc((-home_line-mean)/(p['sigma']*math.sqrt(2)))
    return probability, CANDIDATE_ID


def prop_parameters(mean, sigma, sport, stat, pregame):
    report, _ = artifact()
    if sport != 'ncaaf' or not pregame or stat not in distribution_status()['player_prop_stats']:
        return mean, sigma, None
    p = report['player_props'][stat]['parameters']
    return mean+p['bias_stddev']*sigma, sigma*p['scale_stddev'], CANDIDATE_ID
