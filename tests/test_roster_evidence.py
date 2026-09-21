import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.services import roster_evidence as service


def test_roster_parser_checks_team_season_and_exact_ids():
    team = SimpleNamespace(espn_id="14")
    payload = {
        "team": {"id": "14"},
        "season": {"year": 2026},
        "athletes": [{"items": [{"id": "123", "fullName": "Duplicate Name"}]}],
    }
    assert service.parse(payload, team, 2026) == ["123"]
    with pytest.raises(ValueError):
        service.parse(payload, team, 2025)
    with pytest.raises(ValueError):
        service.parse(payload, SimpleNamespace(espn_id="15"), 2026)


def test_mlb_requires_active_roster_for_the_exact_team():
    payload = {"teamId": 120, "rosterType": "active", "roster": [{"person": {"id": 123}}]}
    assert service.parse_mlb(payload, 120) == ["123"]
    with pytest.raises(ValueError):
        service.parse_mlb(payload, 121)
    with pytest.raises(ValueError):
        service.parse_mlb({**payload, "rosterType": "fullRoster"}, 120)
    with pytest.raises(ValueError):
        service.parse_mlb({**payload, "roster": payload["roster"] * 2}, 120)


async def test_corroboration_uses_ids_not_names_and_rejects_conflicts_and_stale(db, tmp_path):
    from src.models.identity import Player, PlayerExternalId

    player = Player(sport="nfl", full_name="Same Name")
    other = Player(sport="nfl", full_name="Same Name")
    db.add_all([player, other])
    await db.flush()
    db.add(PlayerExternalId(player_id=player.id, source="espn_nfl", external_id="123"))
    await db.flush()
    now = datetime.now(timezone.utc)
    row = dict(
        team_id="home",
        sport="nfl",
        provider="espn_nfl",
        status="verified_roster",
        athlete_ids=["123"],
        observed_at=now.isoformat(),
        season=2026,
        payload_sha256="hash",
        url="source",
    )
    path = tmp_path / "a.json"

    def write(rows, at=now):
        path.write_text(
            json.dumps({"schema_version": 1, "captured_at": at.isoformat(), "teams": rows})
        )

    write([row])
    result = await service.contexts(db, [player, other], {}, tmp_path, now)
    assert result[str(player.id)]["status"] == "corroborated"
    assert result[str(other.id)]["status"] == "roster_unverified"
    game = SimpleNamespace(sport="nfl", season=2026, home_team_id="home", away_team_id="away")
    assert service.reason(result[str(player.id)], game, now) is None
    assert (
        service.reason(result[str(player.id)], game, now + timedelta(hours=13))
        == "player_roster_stale"
    )
    write([row, {**row, "team_id": "away"}])
    assert (await service.contexts(db, [player], {}, tmp_path, now))[str(player.id)][
        "status"
    ] == "conflicting_rosters"
    write([row], now - timedelta(hours=13))
    assert (await service.contexts(db, [player], {}, tmp_path, now))[str(player.id)][
        "status"
    ] == "roster_unverified"
    write([{**row, "status": "unavailable"}])
    assert (await service.contexts(db, [player], {}, tmp_path, now))[str(player.id)][
        "status"
    ] == "roster_unverified"


def test_versioned_football_window_and_market_comparison():
    from src.services.prospective_review import scorecard, protocol

    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    rows = [
        dict(
            captured_at=now,
            game_id=str(i),
            market_key="receptions",
            probability=0.8,
            baseline=0.8,
            market_probability=0.5,
            outcome=1,
            status="graded",
            protocol_verified=True,
        )
        for i in range(220)
    ]
    card = scorecard(
        rows, now + timedelta(days=38), policy=protocol("nfl"), comparison="market_baseline"
    )
    assert card["decision_not_before"] == (now + timedelta(days=127)).isoformat()
    assert "fixed_evaluation_window_not_closed" in card["review"]["blockers"]
    final = scorecard(
        rows, now + timedelta(days=128), policy=protocol("nfl"), comparison="market_baseline"
    )
    assert final["review"][
        "promotion_eligible"
    ]  # Synthetic test evidence, never an approval artifact.
    candidate = scorecard(rows, now + timedelta(days=128), policy=protocol("nfl"))
    assert "both_scores_must_improve" in candidate["review"]["blockers"]
    legacy = scorecard(rows, now + timedelta(days=38))
    assert legacy["window_end"] == (now + timedelta(days=30)).isoformat()


def test_unverified_observations_do_not_start_or_poison_new_window():
    from src.services.prospective_review import scorecard, protocol
    from src.services.forecast_grading import prefer

    now = datetime(2026, 9, 21, tzinfo=timezone.utc)
    row = dict(
        captured_at=now,
        game_id="g",
        market_key="m",
        probability=0.6,
        baseline=0.5,
        market_probability=0.5,
        outcome=None,
        status="pending",
        protocol_verified=False,
    )
    assert scorecard([row], policy=protocol("nfl"))["status"] == "awaiting_verified_forecasts"
    card = scorecard(
        [row, {**row, "captured_at": now + timedelta(days=2), "protocol_verified": True}],
        now,
        policy=protocol("nfl"),
    )
    assert card["window_start"] == (now + timedelta(days=2)).isoformat()
    assert card["unverified_records_excluded"] == 1
    record = {
        "prospective_protocol": protocol("nfl"),
        "prediction": {"sport": "nfl", "forecast_eligible": True},
    }
    old = {
        "prospective_protocol": protocol("nfl"),
        "prediction": {"sport": "nfl", "forecast_eligible": False},
    }
    assert prefer((now + timedelta(minutes=5), "b"), record, ((now, "a"), old))
