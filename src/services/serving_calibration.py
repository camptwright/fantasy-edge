"""Pinned user-authorized override; never auto-load the latest experiment."""
from config.settings import get_settings
from src.services.probability_calibration import transform

CANDIDATE_ID = 'ncaaf-moneyline-sigmoid-20260905-v1'
SLOPE = 2.0
INTERCEPT = -0.25


def deployment_status():
    enabled = get_settings().ncaaf_moneyline_calibration_enabled
    return {'candidate_id': CANDIDATE_ID, 'sport': 'ncaaf', 'market': 'moneyline',
        'enabled': enabled, 'status': 'experimental_user_override' if enabled else 'baseline',
        'slope': SLOPE, 'intercept': INTERCEPT, 'orientation': 'home_win',
        'baseline_retained': True, 'validation_passed': False,
        'approval': 'Explicit user override with baseline retained, 2026-09-05',
        'evaluation_at': '2026-09-05T14:01:33.371555+00:00',
        'holdout_samples': 206, 'baseline_brier': 0.21598847035957836,
        'candidate_brier': 0.20284328889915884,
        'baseline_log_loss': 0.622198193365108, 'candidate_log_loss': 0.5901310458650477,
        'blockers_overridden': ['prospective_validation_pending', 'independent_time_valid_replay_pending',
                               'uncertainty_analysis_pending'],
        'rollback': 'Set NCAAF_MONEYLINE_CALIBRATION_ENABLED=false and recreate api, worker, beat.'}


def calibrate_home_probability(probability, sport, market):
    if sport == 'ncaaf' and market == 'moneyline' and get_settings().ncaaf_moneyline_calibration_enabled:
        return transform(probability, SLOPE, INTERCEPT)
    return probability
