import pytest
from src.services.workspace_player_evidence import uncertainty_evidence, availability_evidence
from src.api.routers.workspace import player_detail
from src.services.workspace_player_evidence import bind_defense_identities


@pytest.mark.asyncio
async def test_sync_persists_fetched_free_agent_identity_pairs(monkeypatch):
    from unittest.mock import AsyncMock
    import httpx
    import src.ingest.espn_fantasy as module
    import src.services.fantasy_score_history as history
    client = AsyncMock()
    client.get.return_value = httpx.Response(200, json={'scoringPeriodId':18,'teams':[]},
                                           request=httpx.Request('GET','https://example.test'))
    save = AsyncMock()
    monkeypatch.setattr(module, '_upsert_league', save)
    monkeypatch.setattr(module, '_snapshot', AsyncMock())
    monkeypatch.setattr(history, 'collect_espn', AsyncMock())
    async def free(client, raw_id, season, week, metadata, projections):
        module._record_player({'id':-999,'defaultPositionId':16,'proTeamId':4},metadata,projections,week)
        return 1
    monkeypatch.setattr(module, '_fetch_free_agents', free)
    for _ in range(2):
        await module._sync_league(AsyncMock(),client,2026,'test','espn:test','owner')
        assert save.await_args.args[-1] == [{'player_id':'-999','team_id':'4'}]


def test_free_agent_metadata_preserves_conflicting_provider_team_ids():
    from src.ingest.espn_fantasy import _record_player
    metadata, projections = {}, {}
    for team in (4, 5, 4):
        _record_player({'id':-999,'defaultPositionId':16,'proTeamId':team}, metadata, projections, 5)
    assert metadata['-999']['provider_team_ids'] == ['4','5']
    assert metadata['-999']['position'] == 'DEF'


def test_espn_ingestion_retains_identity_only_and_preserves_conflicts():
    from src.ingest.espn_fantasy import _defense_identity_evidence
    raw = {'account':'private','teams':[{'owner':'private','roster':{'entries':[
        {'playerPoolEntry':{'player':{'id':-999,'defaultPositionId':16,'proTeamId':4,'name':'ignored'}}},
        {'playerPoolEntry':{'player':{'id':-999,'defaultPositionId':16,'proTeamId':5}}},
        {'playerPoolEntry':{'player':{'id':12,'defaultPositionId':1,'proTeamId':4}}}
    ]}}]}
    assert _defense_identity_evidence(raw) == [
        {'player_id':'-999','team_id':'4'}, {'player_id':'-999','team_id':'5'}]


@pytest.mark.parametrize('pid,team,source,teams,expected', [
    ('CIN', 'CIN', 'sleeper', [{'id':'one','sport':'nfl','abbr':'CIN'}], 'exact_team'),
    ('JAC', 'JAX', 'sleeper', [{'id':'one','sport':'nfl','abbr':'JAX'}], 'exact_team'),
    ('CIN', 'BAL', 'sleeper', [{'id':'one','sport':'nfl','abbr':'BAL'}], 'unresolved_team'),
    ('CIN', 'CIN', 'sleeper', [{'id':'one','sport':'ncaaf','abbr':'CIN'}], 'unresolved_team'),
    ('CIN', 'CIN', 'sleeper', [{'id':'one','sport':'nfl','abbr':'CIN'}, {'id':'two','sport':'nfl','abbr':'CIN'}], 'unresolved_team'),
    ('-4', 'CIN', 'espn', [{'id':'one','sport':'nfl','abbr':'CIN'}], 'unresolved_team'),
    ('CIN', 'CIN', 'sleeper', [], 'unresolved_team'),
])
def test_defense_identity_requires_unique_corroborated_team(pid, team, source, teams, expected):
    player = {'player_id':pid, 'team':team, 'position':'DEF', 'identity_status':'unresolved',
              'weekly_evidence':{'source':source}, 'ros':{'status':'complete_schedule_candidate',
                'full_ros_value':100, 'per_game':{'status':'candidate'}}}
    result = bind_defense_identities({'players':[player]}, teams)['players'][0]
    assert '_workspace_team_identity' not in player
    assert result['identity_status'] == 'unresolved'
    detail = player_detail(result)
    assert detail.identity_status == expected
    assert detail.canonical_team_id == ('one' if expected == 'exact_team' else None)
    assert detail.ros_points is None


def test_individual_player_is_not_resolved_by_team_abbreviation():
    player = {'player_id':'CIN', 'team':'CIN', 'position':'QB'}
    assert bind_defense_identities({'players':[player]}, [])['players'] == [player]


@pytest.mark.parametrize('rows,expected', [
    ([{'player_id':'-999','team_id':'4'}], 'exact_team'),
    ([{'player_id':'-999','team_id':'4'}, {'player_id':'-999','team_id':'4'}], 'exact_team'),
    ([{'player_id':'-999','team_id':'4'}, {'player_id':'-999','team_id':'5'}], 'unresolved_team'),
    ([{'player_id':'-4','team_id':'4'}], 'unresolved_team'),
    ([{'player_id':'-999','team_id':None}], 'unresolved_team'),
])
def test_espn_requires_explicit_provider_team_evidence_not_numeric_id_guess(rows, expected):
    player = {'player_id':'-999','position':'DEF','team':'CIN','identity_status':'unresolved',
              'weekly_evidence':{'source':'espn'}}
    teams = [{'id':'one','sport':'nfl','abbr':'CIN','espn_id':'4'}]
    result = bind_defense_identities({'players':[player]}, teams, rows)['players'][0]
    assert player_detail(result).identity_status == expected
    assert player_detail(result).ros_points is None


def test_reconciled_specialist_history_is_distinct_from_ros():
    player = {'player_id': 'CIN', 'position': 'DEF', 'score_samples': [0, -2, 8],
              'distribution_source': 'reconciled_sleeper_component_history',
              'distribution_evidence': {'status': 'estimated_distribution',
                                       'reconciliation_samples': 9, 'reconciliation_mismatches': 0}}
    result = player_detail(player)
    assert result.distribution.observed_samples == 3
    assert result.distribution.reconciliation_samples == 9
    assert result.distribution.reconciliation_mismatches == 0
    assert result.ros_points is None and result.complete_scored_games is None
    assert result.availability_status == 'team_unit_not_individual_injury_status'


def test_assumed_prior_is_never_counted_as_observed_history():
    result = uncertainty_evidence({'distribution_source': 'assumed_specialist_default',
                                  'score_samples': [1, 2], 'distribution_evidence': {'games': 20}})
    assert result['assumed_prior'] and result['observed_samples'] == 0
    assert result['reconciliation_samples'] is None


def test_nonfinite_and_boolean_samples_are_not_observations():
    result = uncertainty_evidence({'score_samples': [0, -1, True, float('nan'), float('inf'), '1'],
                                  'distribution_evidence': {'reconciliation_samples': True,
                                                            'reconciliation_mismatches': -1}})
    assert result['observed_samples'] == 2
    assert result['reconciliation_samples'] is None
    assert result['reconciliation_mismatches'] is None


@pytest.mark.parametrize('designation,expected', [
    (None, 'unconfirmed_missing_designation'), ('  ', 'unconfirmed_missing_designation'),
    (' active ', 'no_restriction_reported_not_game_clearance'),
    ('IR', 'reported_restriction_requires_review'), ('Questionable', 'reported_restriction_requires_review'),
])
def test_availability_is_not_inferred_from_missing_or_clean_labels(designation, expected):
    assert availability_evidence({'injury_status': designation, 'position': 'RB'}) == expected


def test_missing_evidence_remains_unknown():
    result = player_detail({'player_id': 'missing'})
    assert result.distribution.status == 'unknown'
    assert result.distribution.reconciliation_samples is None
    assert result.availability_status == 'unconfirmed_missing_designation'
