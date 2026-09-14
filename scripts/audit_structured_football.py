"""Reconcile archived Core feeds with saved final summaries; no network/writes to facts."""
import json
from collections import Counter
from pathlib import Path
from config.settings import get_settings
from src.ingest.nfl_results import parse_boxscore
from src.scheduler.calibration import archive
from src.services.football_structured_pbp import reconcile


def run():
    root = Path(get_settings().raw_archive_dir)
    summaries = {}
    for path in sorted((root/'result-observations').glob('*.json'), reverse=True)[:2000]:
        data = json.loads(path.read_text())
        if data.get('provider') in ('espn_nfl', 'espn_ncaaf'):
            summaries.setdefault((data['provider'], str(data['event_id'])), (data['payload'], str(path)))
    reports = []
    evidence = {}
    for path in sorted((root/'football-play-stat-evidence').glob('*.json'), reverse=True)[:100]:
        saved = json.loads(path.read_text())
        evidence.setdefault(saved['core_archive'], (saved['evidence'], str(path)))
    for path in sorted((root/'football-core-pbp').glob('*.json'), reverse=True)[:20]:
        data = json.loads(path.read_text())
        league, event = data['league'], str(data['event_id'])
        provider = 'espn_nfl' if league == 'nfl' else 'espn_ncaaf'
        if (provider, event) not in summaries:
            reports.append({'event_id': event, 'error': 'missing_archived_final_summary'})
            continue
        summary, source = summaries[provider, event]
        play_evidence, evidence_source = evidence.get(str(path), ({}, None))
        report = reconcile(data['payload'], summary, event, league,
                           parse_boxscore(summary, event, optional_trailing_qbr=league == 'college-football'),
                           evidence=play_evidence)
        report['evidence_archive'] = evidence_source
        report.update(core_archive=str(path), summary_archive=source)
        reports.append(report)
    output = archive('football-structured-reconciliation', {'reports': reports, 'serving_enabled': False})
    print(json.dumps({'archive': str(output), 'games': [{
        'event_id': r['event_id'], 'error': r.get('error'), 'timeline_blockers': r.get('timeline_blockers'),
        'unresolved_plays': len(r.get('unresolved_plays', [])),
        'comparisons': dict(Counter(x['state'] for x in r.get('comparisons', [])))} for r in reports]}))


if __name__ == '__main__':
    run()
