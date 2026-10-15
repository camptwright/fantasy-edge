import json
import pytest
from src.api.routers.workspace import qualification_tracks
from src.services.projection_engine_prospective import version


def test_current_report_breakdown_and_blend_labels_are_preserved(tmp_path):
    directory = tmp_path / 'reports'
    directory.mkdir()
    summary = {'n': 4, 'weeks': [1], 'independent_weeks': 2, 'engine_mae': 1, 'sleeper_mae': 2}
    promotion = {'eligible_for_owner_review': True, 'pool': summary, 'required_weeks': 6}
    (directory / 'latest.json').write_text(json.dumps({'version': version(), 'status': 'prospective_research',
        'promotion': promotion, 'by_position': {'WR': summary},
        'by_week': [{'season': 2026, 'week': 1, **summary, 'positions': {'WR': summary}}],
        'candidate_blend': {'all_paired': summary, 'promotion': promotion}}))
    engine, blend = qualification_tracks(tmp_path)[:2]
    assert engine.graded_weeks == 2
    assert engine.current_version and engine.by_position['WR'].n == 4
    assert engine.by_week[0].season == 2026
    assert not blend.eligible_for_owner_review
    assert blend.evidence_type == 'retrospective_reconstructed_current_weights'


def test_old_version_does_not_open_owner_review(tmp_path):
    directory = tmp_path / 'reports'
    directory.mkdir()
    (directory / 'latest.json').write_text(json.dumps({'version': 'old', 'promotion': {
        'eligible_for_owner_review': True, 'pool': {'n': 50, 'weeks': list(range(1, 8))}}}))
    track = qualification_tracks(tmp_path)[0]
    assert not track.eligible_for_owner_review
    assert track.evidence_type == 'historical_older_version'


@pytest.mark.asyncio
async def test_role_history_withholds_player_game_with_pending_correction():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import uuid
    from src.services.role_change_profiles import profile
    game_id = uuid.uuid4()
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    snap = SimpleNamespace(team_id=uuid.uuid4(), offense_snaps=20, offense_pct=.5, observed_at=now, source='nflverse')
    game = SimpleNamespace(id=game_id, season=2026, week=5, game_time=now)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda:[(snap, game)])),
                         scalars=AsyncMock(return_value=SimpleNamespace(all=lambda:[game_id])))
    result = await profile(db, uuid.uuid4(), now=now)
    assert result['games'] == []
    assert result['pending_correction_games_withheld'] == 1
