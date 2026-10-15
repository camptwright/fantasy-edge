from src.services.dynasty_trade_planning import plan
from src.services.role_change_profiles import summarize
from src.services.projection_engine_prospective import starter_pool, summarize as paired_summary


def test_missing_player_value_withholds_package_but_not_known_other_side():
    data = {'players': [{'player_id': 'a'}, {'player_id': 'b'}]}
    market = {'status': 'observed', 'players': [{'player_id': 'a', 'value': 100, 'identity_status': 'exact'}]}
    result = plan(data, ['a'], ['b'], market=market, goal='rebuild')
    assert result['packages']['a']['scenario_package_index'] == 100
    assert result['packages']['b']['scenario_package_index'] is None
    assert result['side_a_market_index_change'] is None


def test_pick_value_requires_source_and_duplicate_pick_is_rejected():
    assert plan({}, [], [], picks=[{'side': 'a', 'season': 2027, 'round': 1, 'value': 10}])['status'] == 'invalid_pick_value'
    pick = {'side': 'a', 'season': 2027, 'round': 1, 'slot': 2, 'value': 10, 'source': 'personal scenario'}
    assert plan({}, [], [], picks=[pick, {**pick, 'side': 'b'}])['status'] == 'duplicate_pick'
    assert plan({}, [], [], picks=[{**pick, 'value': 10**1000}])['status'] == 'invalid_pick_value'


def test_role_missing_measurements_do_not_become_zero_or_trend():
    rows = [{'game_id': str(i), 'kickoff': str(i), 'targets': 2 if i < 3 else None, 'snap_share': .4 + .1 * (i >= 3)} for i in range(6)]
    result = summarize(rows)
    assert result['trends']['targets']['recent'] is None
    assert result['trends']['targets']['change'] is None
    assert result['trends']['snap_share']['change'] == .1


def test_starter_pool_does_not_select_with_hindsight():
    rows = [{'league_id': 'L', 'season': 2026, 'week': 1, 'position': 'QB', 'sleeper': 100-i, 'engine': 100-i, 'actual': 1000 if i == 12 else 0} for i in range(13)]
    assert rows[12] not in starter_pool(rows)


def test_starter_pool_lets_both_sources_choose():
    rows = [{'league_id': 'L', 'season': 2026, 'week': 1, 'position': 'QB', 'sleeper': 100-i, 'engine': 1000 if i == 12 else 0, 'actual': 0} for i in range(14)]
    pool = starter_pool(rows)
    assert rows[12] in pool and rows[13] not in pool


def test_same_week_across_seasons_is_independent_evidence():
    rows = [{'season': s, 'week': 1, 'engine_error': 1, 'sleeper_error': 2, 'engine': 11, 'sleeper': 12, 'actual': 10} for s in (2025, 2026)]
    result = paired_summary(rows)
    assert result['independent_weeks'] == 2
    assert result['ci'] is not None


def test_market_change_uses_matching_format_and_observed_past(tmp_path):
    import json
    from datetime import datetime, timezone
    from src.services.fantasy_market import key
    from src.services.fantasy_market_trends import trends
    params = {'isDynasty': 'true'}
    directory = tmp_path / key(params) / 'snapshots'
    directory.mkdir(parents=True)
    for name, at, value, fmt in [('1', '2026-10-10T12:00:00+00:00', 90, params),
                                 ('2', '2026-10-13T12:00:00+00:00', 100, params),
                                 ('3', '2026-10-14T12:00:00+00:00', 1000, {'isDynasty': 'false'}),
                                 ('4', '2026-10-15T12:00:00+00:00', 2000, params)]:
        (directory / f'{name}.json').write_text(json.dumps({'captured_at': at, 'format': fmt,
                                                          'rows': [{'sleeper_id': 'a', 'value': value}]}))
    result = trends(params, 'sleeper', ['a', 'b'], now=datetime(2026, 10, 14, 12, tzinfo=timezone.utc), archive_root=tmp_path)
    assert result['players'][0]['change'] == 10
    assert result['players'][1]['change'] is None
