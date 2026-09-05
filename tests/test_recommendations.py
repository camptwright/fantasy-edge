"""src/services/recommendations.py - the RAG narrative pipeline.

The LLM call itself is mocked throughout (same pattern as
test_theodds_key_safety.py's httpx.AsyncClient mock) - a real call through
this stack takes ~78s, verified live 2026-09-04, which is exactly why
generate_narrative is never called from a request/response cycle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from src.ingest.identity import resolve_team
from src.models.facts import Game, PlayerGameStat, PlayerPropLine, TeamMarketLine
from src.models.identity import Player
from src.models.ratings import TeamRating
from src.services.recommendations import NO_DATA_NARRATIVE, generate_narrative

FAKE_SETTINGS = SimpleNamespace(
    litellm_api_key="fake-key",
    litellm_base_url="http://litellm:4000/v1",
    fantasy_model_alias="worker",
)


def _mock_client(content: str) -> AsyncMock:
    fake_request = httpx.Request("POST", "http://litellm:4000/v1/chat/completions")
    fake_response = httpx.Response(
        200, request=fake_request, json={"choices": [{"message": {"content": content}}]}
    )
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=fake_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


async def test_raises_without_a_configured_api_key(db):
    settings = SimpleNamespace(litellm_api_key="", litellm_base_url="x", fantasy_model_alias="x")
    with patch("src.services.recommendations.get_settings", return_value=settings):
        try:
            await generate_narrative(db)
            raised = False
        except RuntimeError:
            raised = True
    assert raised


async def test_skips_the_llm_call_entirely_when_there_is_nothing_to_narrate(db):
    mock_client = _mock_client("unused")
    with (
        patch("src.services.recommendations.get_settings", return_value=FAKE_SETTINGS),
        patch("src.services.recommendations.httpx.AsyncClient", return_value=mock_client),
    ):
        narrative = await generate_narrative(db)

    assert narrative == NO_DATA_NARRATIVE
    mock_client.post.assert_not_called()


async def test_calls_the_llm_with_real_signal_and_prop_evidence_when_qualified(db):
    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Los Angeles Chargers")
    db.add(TeamRating(team_id=home.id, sport="nfl", rating=1650.0))
    db.add(TeamRating(team_id=away.id, sport="nfl", rating=1350.0))
    game = Game(
        sport="nfl", espn_event_id="rec-test-1", season=2026,
        home_team_id=home.id, away_team_id=away.id, status="scheduled",
    )
    db.add(game)
    await db.flush()
    now = datetime.now(timezone.utc)
    db.add(TeamMarketLine(game_id=game.id, market="moneyline", side="home", price_american=-150, source="pinnacle", line_type="live", observed_at=now))
    db.add(TeamMarketLine(game_id=game.id, market="moneyline", side="away", price_american=130, source="pinnacle", line_type="live", observed_at=now))

    player = Player(sport="nfl", full_name="Evidence Test Player", current_team_id=home.id)
    db.add(player)
    await db.flush()
    for i, value in enumerate([250.0, 275.0, 300.0, 225.0]):
        stat_game = Game(
            sport="nfl", espn_event_id=f"rec-test-stat-{i}", season=2026,
            home_team_id=home.id, away_team_id=away.id, status="final",
        )
        db.add(stat_game)
        await db.flush()
        db.add(PlayerGameStat(player_id=player.id, game_id=stat_game.id, stat_type="passing_yards", value=value))
    db.add(
        PlayerPropLine(
            player_id=player.id, stat_type="passing_yards", line=200.0,
            over_price_american=-110, under_price_american=-110,
            source="underdog", observed_at=now,
        )
    )
    await db.commit()

    mock_client = _mock_client("Real narrative text.")
    with (
        patch("src.services.recommendations.get_settings", return_value=FAKE_SETTINGS),
        patch("src.services.recommendations.httpx.AsyncClient", return_value=mock_client),
    ):
        narrative = await generate_narrative(db)

    assert narrative == "Real narrative text."
    mock_client.post.assert_awaited_once()
    _, kwargs = mock_client.post.call_args.args, mock_client.post.call_args.kwargs
    evidence_message = kwargs["json"]["messages"][1]["content"]
    # The real matchup and player name must be present verbatim - the
    # model is only ever handed real evidence, never a fabricated stand-in.
    assert "Chiefs" in evidence_message
    assert "Evidence Test Player" in evidence_message


async def test_raises_on_a_blank_completion_instead_of_returning_it(db):
    """FOUND LIVE 2026-09-05: the local Ollama model returned a real HTTP
    200 with an empty completion (no exception to catch on its own).
    Without a check, that empty string was written straight into a new
    RecommendationSnapshot row, silently replacing a real cached narrative
    with nothing - /recommendations then served "no narrative yet" even
    though a good one existed from the prior cycle. Raising here means
    generate_recommendations (src/scheduler/tasks.py) never persists the
    empty result at all - the last good snapshot stays live instead."""
    home = await resolve_team(db, "Kansas City Chiefs")
    away = await resolve_team(db, "Los Angeles Chargers")
    db.add(TeamRating(team_id=home.id, sport="nfl", rating=1650.0))
    db.add(TeamRating(team_id=away.id, sport="nfl", rating=1350.0))
    game = Game(
        sport="nfl", espn_event_id="rec-test-blank", season=2026,
        home_team_id=home.id, away_team_id=away.id, status="scheduled",
    )
    db.add(game)
    await db.flush()
    now = datetime.now(timezone.utc)
    db.add(TeamMarketLine(game_id=game.id, market="moneyline", side="home", price_american=-150, source="pinnacle", line_type="live", observed_at=now))
    db.add(TeamMarketLine(game_id=game.id, market="moneyline", side="away", price_american=130, source="pinnacle", line_type="live", observed_at=now))
    await db.commit()

    for blank in ("", "   \n"):
        mock_client = _mock_client(blank)
        with (
            patch("src.services.recommendations.get_settings", return_value=FAKE_SETTINGS),
            patch("src.services.recommendations.httpx.AsyncClient", return_value=mock_client),
        ):
            try:
                await generate_narrative(db)
                raised = False
            except RuntimeError:
                raised = True
        assert raised, f"blank completion {blank!r} must raise, not be persisted"
