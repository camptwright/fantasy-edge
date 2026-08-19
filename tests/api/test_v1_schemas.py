from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.api.v1.schemas import MarketAssessment, MarketStatus, SourceRef


def test_qualified_assessment_requires_provenance_and_status():
    assessment = MarketAssessment(
        id="a1",
        sport="nfl",
        league="nfl",
        event_id="e1",
        market="moneyline",
        selection="Home",
        status=MarketStatus.qualified,
        probability=0.58,
        sources=[SourceRef(provider="test", snapshot_id="s1", observed_at=datetime.now(UTC))],
        assessed_at=datetime.now(UTC),
    )

    assert assessment.status is MarketStatus.qualified
    assert assessment.sources[0].snapshot_id == "s1"


def test_probability_is_not_accepted_outside_probability_range():
    with pytest.raises(ValidationError):
        MarketAssessment(
            id="a1",
            sport="nfl",
            league="nfl",
            event_id="e1",
            market="moneyline",
            selection="Home",
            status=MarketStatus.qualified,
            probability=1.1,
            assessed_at=datetime.now(UTC),
        )
