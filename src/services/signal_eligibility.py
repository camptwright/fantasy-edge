"""Recommendation eligibility is distinct from displaying research probabilities."""
from datetime import datetime,timezone,timedelta
from src.services.roster_stat_model import finite


def blockers(row, validation=None, *, now=None):
    now=now or datetime.now(timezone.utc); reasons=[]
    if not finite(row.get('ev_percent')) or row['ev_percent']<=0:reasons.append('non_positive_ev')
    if not finite(row.get('kelly_fraction')) or row['kelly_fraction']<=0:reasons.append('no_positive_kelly')
    if not finite(row.get('model_probability')) or not 0<row['model_probability']<1:reasons.append('invalid_probability')
    try:
        kickoff=datetime.fromisoformat(row['game_time'])
        seen=datetime.fromisoformat(row['last_seen_at'])
        if not now<kickoff:reasons.append('event_not_pregame')
        if not timedelta(0)<=now-seen<=timedelta(minutes=45):reasons.append('stale_quote')
    except (KeyError,TypeError,ValueError):reasons.append('missing_valid_quote_timing')
    # Legacy CalibrationReport has no model fingerprint: its passing sport label
    # cannot authorize a different model, override or parameter configuration.
    if not validation:reasons.append('missing_version_bound_validation')
    else:
        if validation.get('passed_gate') is not True:reasons.append('model_validation_failed')
        if not row.get('model_version') or any(validation.get(k)!=row.get(k) for k in ('model_version','sport','market')):
            reasons.append('validation_identity_mismatch')
        try:
            at=datetime.fromisoformat(validation['evaluated_at'])
            if not timedelta(0)<=now-at<=timedelta(days=7):reasons.append('stale_model_validation')
        except (KeyError,TypeError,ValueError):reasons.append('missing_validation_time')
    return reasons
