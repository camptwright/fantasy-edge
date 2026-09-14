import json
from scripts.collect_ncaaf_period_history import cached_reports, summary_digest


def test_previous_report_can_be_resumed_without_refetch(tmp_path):
    (tmp_path/'result-observations').mkdir()
    (tmp_path/'ncaaf-period-history-game').mkdir()
    payload = {'header': {'event': '1'}}
    (tmp_path/'result-observations'/'summary.json').write_text(json.dumps({'payload': payload}))
    report = {'event_id': '1', 'summary_archive': '/old/host/summary.json',
              'timeline_blockers': [], 'unresolved_plays': [],
              'comparisons': [{'state': 'matched'}, {'state': 'mismatch'}]}
    (tmp_path/'ncaaf-period-history-game'/'report.json').write_text(json.dumps(report))
    cached = cached_reports(tmp_path)['1']
    assert cached['summary_sha256'] == summary_digest(payload)
    assert cached['matched'] == 1 and cached['mismatched_or_missing'] == 1
    assert cached['summary_sha256'] != summary_digest({'header': {'event': '1', 'corrected': True}})


def test_explicit_saved_hash_does_not_require_old_host_path(tmp_path):
    (tmp_path/'ncaaf-period-history-game').mkdir()
    report = {'event_id': '1', 'summary_sha256': 'saved', 'timeline_blockers': [],
              'unresolved_plays': [], 'comparisons': []}
    (tmp_path/'ncaaf-period-history-game'/'report.json').write_text(json.dumps(report))
    assert cached_reports(tmp_path)['1']['summary_sha256'] == 'saved'
