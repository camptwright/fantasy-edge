import json

from src.services.context_readiness import readiness


def test_reports_captured_headline_context_without_claiming_structured_inputs(tmp_path):
    forecasts = tmp_path / "forecasts"
    forecasts.mkdir()
    (forecasts / "20260101.json").write_text(json.dumps({"captured_at": "2026-01-01T00:00:00+00:00", "records": [
        {"kind": "player", "feature_snapshot": {"news_evidence_status": "headline_evidence_only", "news_headlines": [{"title": "A"}]}},
        {"kind": "player", "feature_snapshot": {"news_evidence_status": "none", "news_headlines": []}},
        {"kind": "team"},
    ]}))

    report = readiness(tmp_path, rss_configured=True)

    assert report["latest_capture_at"] == "2026-01-01T00:00:00+00:00"
    assert report["player_forecasts"] == 2
    assert report["inputs"][0]["forecast_records_with_evidence"] == 1
    assert report["inputs"][0]["headline_references"] == 1
    assert [row["status"] for row in report["inputs"][1:]] == ["missing_archive", "awaiting_archive", "unavailable", "unavailable", "statistical_outcomes_only"]


def test_handles_no_capture(tmp_path):
    report = readiness(tmp_path, rss_configured=False)
    assert report["latest_capture_at"] is None
    assert report["player_forecasts"] == 0
    assert report["inputs"][0]["status"] == "not_configured"
