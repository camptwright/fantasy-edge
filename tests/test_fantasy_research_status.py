import hashlib
import json
from datetime import datetime, timezone
from src.services.fantasy_research_status import latest, summarize, _read

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def report():
    return dict(league_id='l', season='2026', generated_at=NOW.isoformat(),
                counts={'graded': 2}, new_captures=3, requested_weeks=[5, 6], serving_promoted=True)


def test_status_binds_season_and_never_promotes():
    r = summarize(report(), 'l', '2026', NOW)
    assert r['status'] == 'current' and r['serving_promoted'] is False
    assert r['counts'] == [{'reason': 'graded', 'count': 2}]
    assert summarize(report(), 'other', '2026', NOW)['status'] == 'unavailable'
    assert summarize(report(), 'l', '2027', NOW)['status'] == 'different_season'


def test_future_and_stale_reports():
    p=report(); p['generated_at']='2026-10-11T00:00:00+00:00'
    assert summarize(p,'l','2026',NOW)['status']=='invalid_timestamp'
    p['generated_at']='2026-10-09T00:00:00+00:00'
    assert summarize(p,'l','2026',NOW)['status']=='stale'


def test_missing_corrupt_and_oversized_files_are_bounded(tmp_path):
    folder=tmp_path/'fantasy-retention'/'latest'; folder.mkdir(parents=True)
    path=folder/(hashlib.sha256(b'l').hexdigest()+'.json')
    path.write_text(json.dumps(report()))
    assert latest(tmp_path,'l','2026',NOW)['retention']['status']=='current'
    path.write_text('x'*131073); _read.cache_clear()
    assert latest(tmp_path,'l','2026',NOW)['retention']['status']=='unavailable'
    path.write_text('{'); _read.cache_clear()
    assert latest(tmp_path,'l','2026',NOW)['retention']['status']=='unavailable'
