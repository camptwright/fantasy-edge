"""Durable evaluation freshness; hourly scheduler checks never imply success."""
import json
from datetime import datetime, timezone


def latest(directory):
    for path in sorted(directory.glob('*.json'), reverse=True):
        try:
            payload = json.loads(path.read_text())
            return payload, str(path)
        except (OSError, ValueError):
            continue
    return {}, None


def version_matches(report, current):
    evaluated=report.get('serving_version_manifest',{})
    return all(current.get(key) and evaluated.get(key)==current[key]
               for key in ('model_version','policy_version','cohort_version'))


def completed_today(report, sports, now, current=None):
    try:
        stamp = datetime.fromisoformat(report['completed_at'])
        return (report.get('status') == 'complete' and stamp.tzinfo is not None and
                stamp <= now and stamp.date() == now.date() and set(report['sports']) == set(sports)
                and (current is None or version_matches(report,current)))
    except (KeyError, TypeError, ValueError):
        return False


def status(root, sports, now=None):
    from src.services.model_version import manifest
    current=manifest()
    now = now or datetime.now(timezone.utc)
    report, path = latest(root/'calibration')
    attempt, _ = latest(root/'evaluation-runs')
    if attempt.get('status') == 'running':
        try:
            started = datetime.fromisoformat(attempt['started_at'])
            if (now - started).total_seconds() > 1900:
                attempt = {**attempt, 'status': 'abandoned',
                           'reason': 'Exceeded worker hard time limit without completion.'}
        except (KeyError, ValueError, TypeError):
            attempt = {**attempt, 'status': 'unknown'}
    try:
        stamp = datetime.fromisoformat(report.get('completed_at', report.get('evaluated_at', '')))
        age = (now-stamp).total_seconds()
        fresh = stamp.tzinfo is not None and 0 <= age <= 26*3600 and report.get('status') == 'complete'
    except (ValueError, TypeError):
        fresh = False
    compatible=version_matches(report,current)
    return {'status': 'current' if fresh and compatible else 'version_mismatch' if fresh else 'overdue_or_incomplete',
        'completed_today_utc': completed_today(report, sports, now,current),
        'operationally_fresh':fresh,'serving_version_evaluated':compatible,
        'evaluated_versions':{k:report.get('serving_version_manifest',{}).get(k) for k in ('model_version','policy_version','cohort_version')},
        'current_versions':{k:current[k] for k in ('model_version','policy_version','cohort_version')},
        'latest_report': path, 'latest_completed_at': report.get('completed_at'),
        'latest_attempt': attempt, 'report_status': report.get('status', 'legacy_or_missing'),
        'schedule': 'Hourly catch-up; one complete evaluation per UTC day. Failed/partial runs retry next check.',
        'automatic_promotion': False}
