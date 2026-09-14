import json
from datetime import datetime, timedelta, timezone

from src.services.news_evidence import headlines_for_players


def test_headline_evidence_is_exact_name_bounded_and_asof_safe(tmp_path):
    now = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)
    rows = [
        {'title': 'Drake Maye practices fully', 'url': 'https://example/one', 'source': 'rss',
         'observed_at': (now-timedelta(minutes=1)).isoformat()},
        {'title': 'Drake Maye practices fully', 'url': 'https://example/one', 'source': 'rss',
         'observed_at': (now-timedelta(minutes=2)).isoformat()},
        {'title': 'Drake Maye update', 'url': 'https://example/future', 'source': 'rss',
         'observed_at': (now+timedelta(minutes=1)).isoformat()},
        {'title': 'Maye is ready', 'url': 'https://example/partial', 'source': 'rss',
         'observed_at': now.isoformat()},
    ]
    (tmp_path / 'news.json').write_text(json.dumps(rows))
    found = headlines_for_players(tmp_path, {'p': 'Drake Maye', 'other': 'Josh Allen'}, now)
    assert found['p'] == [{'title': 'Drake Maye practices fully', 'url': 'https://example/one',
                            'source': 'rss', 'observed_at': (now-timedelta(minutes=1)).isoformat()}]
    assert found['other'] == []


def test_bad_archives_and_non_list_payloads_are_ignored(tmp_path):
    (tmp_path / 'bad.json').write_text('{')
    (tmp_path / 'object.json').write_text('{}')
    assert headlines_for_players(tmp_path, {'p': 'Player Name'}, datetime.now(timezone.utc)) == {'p': []}
