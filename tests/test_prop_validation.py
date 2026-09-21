import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.services import prop_validation as service


def identities():
    return (
        SimpleNamespace(sport="nfl", current_team_id="home"),
        SimpleNamespace(
            id="game",
            sport="nfl",
            home_team_id="home",
            away_team_id="away",
            game_time=datetime(2027, 1, 1, tzinfo=timezone.utc),
        ),
    )


def row():
    from src.ingest.prop_events import event_binding

    return dict(
        event_binding=event_binding(identities()[1]),
        model_probability=0.56,
        market_fair_probability=0.5,
        over_price_american=-110,
        under_price_american=-110,
        line=2.5,
        edge_percent=6.9,
        under_edge_percent=-16,
    )


def test_missing_validation_does_not_authorize_baseline():
    assert service.assess(row(), *identities(), None) == ["missing_version_bound_prop_validation"]
    assert service.assess(row(), *identities(), {"status": "approved"}) == []


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("current_team_id", None, "player_team_unverified"),
        ("current_team_id", "other", "player_game_team_mismatch"),
        ("sport", "nba", "player_game_sport_mismatch"),
    ],
)
def test_player_event_evidence(field, value, reason):
    player, game = identities()
    setattr(player, field, value)
    assert service.linkage(player, game) == reason


def test_large_edges_and_integer_pushes_stay_research_even_with_model_approval():
    candidate = {**row(), "model_probability": 0.96, "edge_percent": 80, "line": 2}
    reasons = service.assess(candidate, *identities(), {"status": "approved"})
    assert "large_edge_requires_review" in reasons
    assert "integer_line_requires_push_model" in reasons


def test_binding_must_match_current_event_schedule():
    player, game = identities()
    binding = row()["event_binding"]
    assert service.binding_reason(binding, game) is None
    game.game_time += timedelta(hours=1)
    assert service.binding_reason(binding, game) == "provider_event_binding_changed"
    assert service.binding_reason(None, game) == "provider_event_binding_unverified"


def test_decision_digest_preserves_unchanged_regrade_not_changed_metrics():
    record = dict(
        sport="nfl",
        kind="player",
        market="receptions",
        model_version="cohort",
        prospective_scorecard={"policy_id": "fixed", "review": {"promotion_eligible": True}},
    )
    digest = service.decision_digest(record)
    assert service.decision_digest({**record, "graded_at": "later"}) == digest
    assert service.decision_digest({**record, "model_version": "new"}) != digest


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "old_version",
        "changed_bytes",
        "failed",
        "stale",
        "future",
        "unapproved",
        "few_games",
    ],
)
def test_only_exact_fresh_passed_approved_report_can_authorize(tmp_path, monkeypatch, change):
    now = datetime.now(timezone.utc)
    versions = {"model_version": "model", "cohort_version": "cohort"}
    record = dict(
        kind="player",
        sport="nfl",
        market="receptions",
        model_version="cohort",
        sample_size=500,
        independent_games=250,
        prospective_scorecard={
            "decision_not_before": (now - timedelta(days=1)).isoformat(),
            "review": {"promotion_eligible": True, "blockers": [], "independent_games": 250},
        },
    )
    report = {
        "schema_version": 1,
        "status": "available",
        "graded_at": now.isoformat(),
        "reports": [record],
    }
    if change == "failed":
        record["prospective_scorecard"]["review"]["blockers"] = ["does_not_beat_market_benchmark"]
    if change == "few_games":
        record["independent_games"] = 2
    if change == "stale":
        report["graded_at"] = (now - timedelta(hours=3)).isoformat()
    if change == "future":
        report["graded_at"] = (now + timedelta(hours=1)).isoformat()
    if change == "old_version":
        record["model_version"] = "old"
    raw = json.dumps(report).encode()
    grading = tmp_path / "grading"
    grading.mkdir()
    path = grading / "report.json"
    path.write_bytes(raw)
    approved = tmp_path / "approved.json"
    approved.write_text(
        json.dumps(
            [
                dict(
                    approved=change != "unapproved",
                    sport="nfl",
                    market="receptions",
                    **versions,
                    decision_sha256=service.decision_digest(record),
                )
            ]
        )
    )
    monkeypatch.setattr(service, "APPROVALS", approved)
    if change == "changed_bytes":
        record["prospective_scorecard"]["window_records"] = 900
        path.write_text(json.dumps(report))
    result = service.load_evidence(grading, versions, now)
    assert bool(result) == (change == "none")


async def test_exact_event_resolution_rejects_adjacent_and_duplicate_games(db):
    from src.ingest.identity import resolve_team
    from src.ingest.prop_events import match_priced_event
    from src.models.facts import Game

    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Buffalo Bills")
    kickoff = datetime.now(timezone.utc) + timedelta(days=1)
    game = Game(
        sport="nfl", season=2026, home_team_id=home.id, away_team_id=away.id, game_time=kickoff
    )
    db.add(game)
    await db.flush()
    event = dict(home_team=home.name, away_team=away.name, commence_time=kickoff.isoformat())
    assert (await match_priced_event(db, event, "nfl")).id == game.id
    assert (
        await match_priced_event(
            db, {**event, "commence_time": (kickoff + timedelta(hours=3)).isoformat()}, "nfl"
        )
        is None
    )
    assert await match_priced_event(db, {**event, "commence_time": None}, "nfl") is None
    db.add(
        Game(
            sport="nfl", season=2026, home_team_id=home.id, away_team_id=away.id, game_time=kickoff
        )
    )
    await db.flush()
    assert await match_priced_event(db, event, "nfl") is None


async def test_serving_needs_approval_but_valid_research_can_still_be_captured(db, monkeypatch):
    from src.ingest.identity import resolve_team
    from src.ingest.lines import record_prop_line
    from src.ingest.prop_events import event_binding
    from src.models.facts import Game, PlayerGameStat
    from src.models.identity import Player
    from src.api.routers.sportsbook import prop_rows
    from src.services.forecast_capture import capture

    now = datetime.now(timezone.utc)
    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Buffalo Bills")
    player = Player(sport="nfl", full_name="Validation fixture", current_team_id=home.id)
    game = Game(
        sport="nfl",
        season=2026,
        status="scheduled",
        home_team_id=home.id,
        away_team_id=away.id,
        game_time=now + timedelta(days=1),
    )
    db.add_all([player, game])
    await db.flush()
    for i in range(4):
        past = Game(sport="nfl", season=2026, status="final", game_time=now - timedelta(days=i + 1))
        db.add(past)
        await db.flush()
        db.add(
            PlayerGameStat(
                player_id=player.id, game_id=past.id, stat_type="receptions", value=i + 1
            )
        )
    await record_prop_line(
        db,
        player_id=player.id,
        game_id=game.id,
        stat_type="receptions",
        line=2.5,
        over_price_american=120,
        under_price_american=-150,
        source="test",
        event_binding=event_binding(game),
    )
    await db.commit()
    monkeypatch.setattr(service, "load_evidence", lambda *args: {})
    research = (await prop_rows(db, "nfl"))[0]
    assert not research["actionable"] and research["forecast_eligible"]
    await db.commit()
    captured = await capture(db)
    assert len(captured["records"]) == 1
    assert captured["records"][0]["prediction"]["forecast_eligible"]
    assert not captured["records"][0]["prediction"]["actionable"]
    await db.commit()
    monkeypatch.setattr(
        service, "load_evidence", lambda *args: {("nfl", "receptions"): {"status": "approved"}}
    )
    assert (await prop_rows(db, "nfl"))[0]["actionable"]
    game.game_time += timedelta(hours=1)
    await db.flush()
    changed = (await prop_rows(db, "nfl"))[0]
    assert not changed["actionable"] and not changed["forecast_eligible"]
    assert "provider_event_binding_changed" in changed["recommendation_blockers"]
