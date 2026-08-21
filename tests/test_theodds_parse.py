"""Parser verified against a captured live payload, not against memory."""

from __future__ import annotations

import json
from pathlib import Path

from src.ingest.theodds import _rows_for

FIXTURE = Path(__file__).parent / "fixtures" / "theodds_nfl.json"


def test_first_event_yields_all_three_markets():
    event = json.loads(FIXTURE.read_text())[0]
    rows = _rows_for(event)
    assert {r["market"] for r in rows} == {"moneyline", "spread", "total"}


def test_spread_sides_mirror_each_other():
    event = json.loads(FIXTURE.read_text())[0]
    spreads = {r["side"]: r["line"] for r in _rows_for(event) if r["market"] == "spread"}
    assert spreads["home"] == -spreads["away"]


def test_moneyline_carries_no_handicap():
    event = json.loads(FIXTURE.read_text())[0]
    assert all(
        r["line"] is None for r in _rows_for(event) if r["market"] == "moneyline"
    )


def test_total_sides_share_one_number():
    event = json.loads(FIXTURE.read_text())[0]
    totals = {r["side"]: r["line"] for r in _rows_for(event) if r["market"] == "total"}
    assert totals["over"] == totals["under"]
