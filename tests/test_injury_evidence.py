import json
from datetime import datetime, timezone
from src.services.injury_evidence import fresh_rows, unavailable


def test_rejects_stale_and_future_evidence(tmp_path):
    now = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
    rows = [{'observed_at': observed, 'reported_at': reported} for observed, reported in [
        ('2026-09-07T11:30:00+00:00', '2026-09-06T12:00Z'),
        ('2026-09-07T10:00:00+00:00', '2026-09-06T12:00Z'),
        ('2026-09-07T13:00:00+00:00', '2026-09-06T12:00Z'),
        ('2026-09-07T11:30:00+00:00', '2026-08-01T12:00Z')]]
    (tmp_path/'1.json').write_text(json.dumps(rows))
    assert fresh_rows(tmp_path, now) == rows[:1]
    (tmp_path/'2.json').write_text('[]')
    assert fresh_rows(tmp_path, now) == []


def test_only_unambiguous_official_injured_status_excludes():
    def context(*statuses):
        return {'reports': [{'provider': 'mlb_stats_api', 'status': status} for status in statuses]}
    assert unavailable(context('D10'))
    assert unavailable(context('D10', 'D60'))
    assert not unavailable(context('D10', 'A'))
    assert not unavailable(context('A'))
    assert not unavailable({'reports': [{'provider': 'espn_public_injuries', 'status': 'Out'}]})
    assert not unavailable(None)
