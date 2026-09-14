"""Truthful readiness for non-statistical forecast context.

This deliberately reports evidence availability instead of treating a missing
feed as a neutral injury, lineup, weather, or settlement outcome.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from datetime import datetime, timezone
from src.services.injury_evidence import archive_rows, game_snapshots, age


def _latest_payload(archive_dir: Path) -> object | None:
    paths = sorted(archive_dir.glob("*.json"))
    if not paths:
        return None
    try:
        payload = json.loads(paths[-1].read_text())
    except (OSError, ValueError):
        return None
    return payload


def _latest_capture(archive_dir: Path) -> dict | None:
    payload = _latest_payload(archive_dir)
    return payload if isinstance(payload, dict) and isinstance(payload.get("records"), list) else None


def readiness(raw_archive_dir: Path, rss_configured: bool) -> dict:
    """Summarize immutable captured evidence, never current page content."""
    capture = _latest_capture(raw_archive_dir / "forecasts")
    player_records = [] if capture is None else [r for r in capture["records"] if r.get("kind") == "player"]
    statuses = Counter((r.get("feature_snapshot") or {}).get("news_evidence_status", "no_feature_snapshot")
                       for r in player_records)
    headline_refs = sum(len((r.get("feature_snapshot") or {}).get("news_headlines", [])) for r in player_records)
    injury_archive = _latest_payload(raw_archive_dir / "espn_injuries")
    injury_rows = injury_archive if isinstance(injury_archive, list) else []
    now = datetime.now(timezone.utc)
    _, injury_state = archive_rows(raw_archive_dir / 'espn_injuries', now)
    events = game_snapshots(raw_archive_dir / 'football_availability', now)
    coverage = Counter()
    for event in events.values():
        try:
            label = event['coverage'] if 0 <= age(event['observed_at'], now) <= 3600 else 'stale'
        except (ValueError, TypeError, KeyError, AttributeError):
            label = 'invalid'
        coverage[(event.get('sport', 'unknown'), label)] += 1
    return {
        "latest_capture_at": capture.get("captured_at") if capture else None,
        "player_forecasts": len(player_records),
        "inputs": [
            {"name": "RSS headline evidence", "status": "research_only" if rss_configured else "not_configured",
             "forecast_records_with_evidence": statuses["headline_evidence_only"],
             "headline_references": headline_refs,
             "note": "Exact-name, timestamp-bounded headline references; never a numeric adjustment or injury/lineup confirmation."},
            {"name": "ESPN professional injury reports", "status": injury_state,
             "report_records": len(injury_rows),
             "note": "Timestamped NFL/NBA/MLB/NHL ESPN reports. Only a verified source-specific athlete identity may link a report to a forecast; never inferred as healthy."},
            {"name": "NFL/NCAAF game-linked availability", "status": "partial_evidence" if events else "awaiting_archive",
             "coverage": [{'sport': sport, 'status': label, 'games': count} for (sport, label), count in sorted(coverage.items())],
             "note": "ESPN event-page team injury evidence, not official inactive lists. Missing NCAAF injury sections are explicitly not provided. No numeric injury adjustment."},
            {"name": "Confirmed starting lineup", "status": "unavailable",
             "note": "No authoritative pregame lineup feed is configured; historical opportunity is not a future-role confirmation."},
            {"name": "Timestamped venue weather", "status": "unavailable",
             "note": "No venue-coordinate weather source with observation timestamps is configured; unverified game weather is not modeled."},
            {"name": "Bookmaker settlement", "status": "statistical_outcomes_only",
             "note": "Grading uses recorded statistical outcomes and pushes. It does not represent operator-specific DNP, postponement, or void rules."},
        ],
        "note": "Unavailable context remains explicit and cannot silently influence an actionable prediction.",
    }
