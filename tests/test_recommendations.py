"""Numeric summaries do not require an LLM or API key."""

from unittest.mock import AsyncMock
import pytest
from src.services import recommendations as service


def signal():
    return dict(
        id="s",
        actionable=True,
        sport="nfl",
        matchup="A @ B",
        selection="B ML",
        bookmaker="test",
        price_american=135,
        model_probability=0.5663,
    )


def prop():
    return dict(
        id="p",
        actionable=True,
        sport="nfl",
        player_name="Player",
        stat_type="receptions",
        line=5.5,
        source="test",
        over_price_american=-110,
        under_price_american=-110,
        model_probability=0.3,
        under_model_probability=0.7,
    )


def test_comparison_direction_and_units_are_computed():
    row = service.quote_summary(signal(), "signal")
    assert "56.63% is above" in row["text"]
    assert "42.55%" in row["text"]
    assert "EV +33.08% per unit staked" in row["text"]


def test_under_selection_keeps_under_odds_and_probability():
    row = service.quote_summary(prop(), "prop")
    assert "Under 5.5 receptions" in row["text"] and "70.00%" in row["text"]
    assert "EV +33.64%" in row["text"]


@pytest.mark.parametrize(
    "change",
    [
        {"actionable": False},
        {"model_probability": float("nan")},
        {"model_probability": 0.1},
        {"price_american": None},
        {"price_american": 0},
        {"price_american": True},
    ],
)
def test_invalid_or_unqualified_quotes_are_never_narrated(change):
    assert service.quote_summary({**signal(), **change}, "signal") is None


async def test_empty_data_needs_no_llm_key_or_network(monkeypatch):
    monkeypatch.setattr(service, "signal_rows", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "prop_rows", AsyncMock(return_value=[]))
    result = await service.generate_narrative(None, with_evidence=True)
    assert result == {"narrative": service.NO_DATA_NARRATIVE, "quote_ids": []}


async def test_deterministic_order_and_exact_quote_ids(monkeypatch):
    rows = [signal(), {**signal(), "id": "excluded", "actionable": False}]
    monkeypatch.setattr(service, "signal_rows", AsyncMock(return_value=rows))
    monkeypatch.setattr(service, "prop_rows", AsyncMock(return_value=[prop()]))
    first = await service.generate_narrative(None, with_evidence=True)
    assert first == await service.generate_narrative(None, with_evidence=True)
    assert first["quote_ids"] == ["p", "s"]
    assert first["narrative"].startswith(service.NARRATIVE_VERSION)
    assert "not American odds" in first["narrative"]


async def test_legacy_llm_cache_is_withheld():
    from types import SimpleNamespace
    from datetime import datetime, timezone

    db = AsyncMock()
    db.scalar.return_value = SimpleNamespace(
        narrative="Model probability .56 is lower than .42",
        quote_ids=[],
        generated_at=datetime.now(timezone.utc),
    )
    assert (await service.get_valid_narrative(db))["narrative"] is None


def test_prop_ranking_includes_under_only_edges():
    assert service.prop_edge({"edge_percent": -20, "under_edge_percent": 15}) == 15


async def test_cached_numbers_are_revalidated_even_when_quote_id_is_unchanged(monkeypatch):
    from types import SimpleNamespace
    from datetime import datetime, timezone
    from uuid import uuid4

    row = {**signal(), "id": str(uuid4())}
    signals = AsyncMock(return_value=[row])
    monkeypatch.setattr(service, "signal_rows", signals)
    monkeypatch.setattr(service, "prop_rows", AsyncMock(return_value=[]))
    cached = await service.generate_narrative(None, with_evidence=True)
    db = AsyncMock()
    db.scalar.return_value = SimpleNamespace(**cached, generated_at=datetime.now(timezone.utc))
    assert (await service.get_valid_narrative(db))["narrative"] == cached["narrative"]
    signals.return_value = [{**row, "model_probability": 0.6}]
    assert (await service.get_valid_narrative(db))["narrative"] is None
