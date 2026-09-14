"""Bounded public Core collection for archived completed college games."""
import json
import hashlib
from pathlib import Path
import httpx
from config.settings import get_settings
from src.scheduler.calibration import archive
from src.ingest.nfl_results import parse_boxscore
from src.services.football_structured_pbp import reconcile


def summary_digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def cached_reports(root):
    result = {}
    for path in sorted((root/'ncaaf-period-history-game').glob('*.json')):
        saved = json.loads(path.read_text())
        digest = saved.get('summary_sha256')
        if digest is None:
            # Existing reports predate the hash. Resolve only the basename
            # inside the trusted archive directory, not arbitrary saved paths.
            source = root/'result-observations'/Path(saved['summary_archive']).name
            if source.exists():
                digest = summary_digest(json.loads(source.read_text())['payload'])
        result[saved['event_id']] = {'event_id': saved['event_id'], 'report': str(path),
            'summary_sha256': digest, 'timeline_blockers': saved['timeline_blockers'],
            'unresolved_plays': len(saved['unresolved_plays']),
            'matched': sum(r['state'] == 'matched' for r in saved['comparisons']),
            'mismatched_or_missing': sum(r['state'] != 'matched' for r in saved['comparisons'])}
    return result


def run():
    root = Path(get_settings().raw_archive_dir)
    reports, seen, requests = cached_reports(root), set(), 0
    with httpx.Client(timeout=20, follow_redirects=False) as client:
        for path in sorted((root/'result-observations').glob('*.json'), reverse=True)[:2000]:
            saved = json.loads(path.read_text())
            if saved.get('provider') != 'espn_ncaaf':
                continue
            event = str(saved['event_id'])
            if event in seen or not event.isdigit():
                continue
            seen.add(event)
            digest = summary_digest(saved['payload'])
            if reports.get(event, {}).get('summary_sha256') == digest:
                continue
            try:
                box = parse_boxscore(saved['payload'], event, optional_trailing_qbr=True)
                url = f'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/events/{event}/competitions/{event}/plays'
                requests += 1
                response = client.get(url, params={'limit': 1000})
                response.raise_for_status()
                core = response.json()
                core_path = archive('football-core-pbp', {'league': 'college-football', 'event_id': event, 'payload': core})
                result = reconcile(core, saved['payload'], event, 'college-football', box)
                result.update(core_archive=core_path, summary_archive=str(path), summary_sha256=digest)
                report_path = archive('ncaaf-period-history-game', result)
                reports[event] = {'event_id': event, 'report': report_path, 'summary_sha256': digest,
                    'timeline_blockers': result['timeline_blockers'],
                    'unresolved_plays': len(result['unresolved_plays']),
                    'matched': sum(r['state'] == 'matched' for r in result['comparisons']),
                    'mismatched_or_missing': sum(r['state'] != 'matched' for r in result['comparisons'])}
            except (ValueError, KeyError, httpx.HTTPError) as exc:
                reports[event] = {'event_id': event, 'error_type': type(exc).__name__}
            if requests >= 10:
                break
    output = {'games': len(reports), 'request_cap': 10, 'requests_this_run': requests,
              'reports': list(reports.values()), 'serving_enabled': False}
    print(json.dumps({'archive': archive('ncaaf-period-history-status', output), **output}))


if __name__ == '__main__':
    run()
