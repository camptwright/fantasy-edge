"""Grading history as deltas: exact reconstruction, tamper evidence, latest pointer."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.services import evidence_delta as ed
from src.services import forecast_evidence as fe


def report(n, changed=None, graded_at="2026-10-13T00:00:00+00:00"):
    rows = [{"sport": "nfl", "market": f"m{i}", "brier": 0.2 + i / 1000, "scorecard": {"bins": list(range(60))}} for i in range(n)]
    if changed is not None:
        rows[changed]["brier"] = 0.9
    return {"schema_version": 1, "status": "available", "graded_at": graded_at, "counts": {"graded": n},
            "reports": rows, "shadow_reports": rows[:2]}


def test_delta_stores_only_changed_rows_and_rebuilds_exactly():
    a, b = report(50), report(50, changed=7, graded_at="2026-10-13T00:30:00+00:00")
    first = ed.delta(None, a, ("reports", "shadow_reports"))
    second = ed.delta(a, b, ("reports", "shadow_reports"))
    assert len(first["lists"]["reports"]["added"]) == 50 and len(second["lists"]["reports"]["added"]) == 1
    assert ed.replay(ed.apply(None, first), [second]) == b
    assert len(json.dumps(second)) < len(json.dumps(b)) / 3


def test_tampering_or_a_wrong_base_is_detected():
    a, b = report(5), report(5, changed=1)
    change = ed.delta(a, b, ("reports",))
    with pytest.raises(ValueError, match="base"):
        ed.apply(report(4), change)
    change["lists"]["reports"]["added"][next(iter(change["lists"]["reports"]["added"]))]["brier"] = 0.1
    with pytest.raises(ValueError, match="digest"):
        ed.apply(a, change)


async def test_save_grading_keeps_one_latest_row_and_delta_history(db):
    from sqlalchemy import func, select
    from src.models.governance import ForecastArchive
    now = datetime.now(timezone.utc)
    a, b = report(20, graded_at=now.isoformat()), report(20, changed=3, graded_at=(now + timedelta(minutes=30)).isoformat())
    await fe.save_grading(db, a)
    change = await fe.save_grading(db, b)
    await db.commit()
    assert len(change["lists"]["reports"]["added"]) == 1
    latest = await fe.latest_grade(db)
    assert latest["reports"][3]["brier"] == 0.9 and latest["stale"] is False
    kinds = dict((await db.execute(select(ForecastArchive.kind, func.count()).group_by(ForecastArchive.kind))).all())
    assert kinds == {"grading_delta": 2}


def test_keyframe_daily_latest_pointer_and_reader(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.scheduler import calibration
    from src.services import prop_validation, raw_retention
    monkeypatch.setattr(calibration, "get_settings", lambda: SimpleNamespace(raw_archive_dir=str(tmp_path)))
    a = report(3)
    first = calibration.archive_grading(a, ed.delta(None, a, ("reports",)))
    second = calibration.archive_grading(a, ed.delta(a, a, ("reports",)))
    assert "keyframe" in first and "keyframe" not in second  # at most one full copy a day
    assert json.loads((tmp_path / "grading" / "_latest.json").read_text()) == a
    assert len(list((tmp_path / "grading" / "deltas").glob("*.json"))) == 2
    # the validation reader prefers the pointer, so a newer delta file is never read as a report
    monkeypatch.setattr(prop_validation, "APPROVALS", tmp_path / "approvals.json")
    (tmp_path / "approvals.json").write_text("{}")
    assert prop_validation.load_evidence(tmp_path / "grading", {"cohort_version": "x"},
                                         datetime.fromisoformat(a["graded_at"])) == {}
    old = datetime.now(timezone.utc) + timedelta(days=3)
    done = raw_retention.compress_daily(now=old, root=tmp_path)
    assert (tmp_path / "grading" / "_latest.json").exists() and done["compressed"] >= 3


def test_roster_payloads_are_kept_only_when_membership_changes():
    from src.services.roster_evidence import drop_unchanged_payloads
    row = lambda team, ids: {"team_id": team, "status": "verified_roster", "athlete_ids": ids, "payload_sha256": "h", "payload": {"big": 1}}
    previous = {"teams": [row("a", ["1", "2"]), row("b", ["3"])]}
    current = {"teams": [row("a", ["2", "1"]), row("b", ["3", "4"]), row("c", ["9"]), {"team_id": "d", "status": "unavailable"}]}
    assert drop_unchanged_payloads(current, previous) == 2
    a, b, c, _ = current["teams"]
    assert "payload" not in a and a["payload_retained"] == "unchanged_membership" and a["payload_sha256"] == "h"
    assert "payload" in b and "payload" in c
