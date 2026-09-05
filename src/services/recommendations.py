"""LLM narrative generation over real signals/props - a RAG pipeline, not
model fine-tuning. The model only narrates and ranks already-computed
evidence; it never produces its own probability/EV numbers - those keep
coming from src/services/elo.py/totals.py/projections.py via the exact same
signal_rows/prop_rows this app's /signals and /props already serve.
Mirrors src/api/main.py's fantasy_advice endpoint's evidence-only framing.

One combined narrative across every sport, not one per sport - a real
generation call through this stack's local Ollama model took ~78s
(verified live 2026-09-04, no GPU acceleration for a 9B model on this Mac
mini), so five per-sport calls would eat most of a 30-minute beat cycle.
See src/scheduler/tasks.py's fantasy.generate_recommendations, which is
the only caller - this never runs inside an HTTP request/response cycle.
"""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.api.routers.sportsbook import prop_rows, signal_rows

_TOP_N = 8

_SYSTEM_PROMPT = (
    "You are a sports betting analyst. Use only the supplied JSON evidence - "
    "never invent a probability, price, or player detail not present in it. "
    "Identify the most interesting signals and props across every sport "
    "given, explain briefly why each stands out (edge percent, and model "
    "probability versus the market's implied probability where given), and "
    "group your write-up by sport. State plainly that these are "
    "probabilistic edges from a transparent baseline model, not calibrated "
    "predictions or guaranteed outcomes, and that this is not gambling "
    "advice."
)

NO_DATA_NARRATIVE = "No priced signals or qualified props are available yet."


async def generate_narrative(db: AsyncSession) -> str:
    settings = get_settings()
    if not settings.litellm_api_key:
        raise RuntimeError("LITELLM_API_KEY is not configured")

    signals = sorted(
        (row for row in await signal_rows(db, sport=None) if row["price_american"] is not None),
        key=lambda row: row["ev_percent"],
        reverse=True,
    )[:_TOP_N]
    props = sorted(
        (row for row in await prop_rows(db, sport=None) if row["edge_percent"] is not None),
        key=lambda row: row["edge_percent"],
        reverse=True,
    )[:_TOP_N]

    if not signals and not props:
        # Nothing to narrate yet - skip the ~78s round trip entirely rather
        # than asking the model to comment on empty evidence.
        return NO_DATA_NARRATIVE

    evidence = {
        "signals": [
            {
                "sport": row["sport"],
                "matchup": row["matchup"],
                "market": row["market"],
                "selection": row["selection"],
                "price_american": row["price_american"],
                "model_probability": row["model_probability"],
                "implied_probability": row["implied_probability"],
                "ev_percent": row["ev_percent"],
            }
            for row in signals
        ],
        "props": [
            {
                "sport": row["sport"],
                "player_name": row["player_name"],
                "stat_type": row["stat_type"],
                "line": row["line"],
                "projection": row["projection"],
                "edge_percent": row["edge_percent"],
            }
            for row in props
        ],
    }

    # 180s wasn't enough live: a real 5-sport, 16-item evidence payload
    # (the realistic case, not the 1-signal smoke test that measured ~78s)
    # timed out against it. 480s gives real headroom - this always runs
    # from a Celery task on a 30-minute cadence, never a request/response
    # cycle, so a slow generation just delays this cycle's row, not a user.
    async with httpx.AsyncClient(base_url=settings.litellm_base_url, timeout=480) as client:
        response = await client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {settings.litellm_api_key}"},
            json={
                "model": settings.fantasy_model_alias,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": str(evidence)},
                ],
                "temperature": 0.2,
                # FOUND LIVE 2026-09-05: this model is a "thinking" model
                # that emits its chain-of-thought as a separate
                # `reasoning_content` field before ever writing the real
                # answer into `content`. Verified live: a 1-signal prompt
                # finished in ~2.4k total tokens with real content; the
                # real 16-item, 5-sport evidence payload burns enough
                # reasoning tokens that without headroom the response gets
                # cut off while still "thinking" - content empty,
                # reasoning_content populated, finish_reason cut short.
                # No max_tokens was set before, so this rode whatever
                # Ollama's own num_predict default is - too small for this
                # model's reasoning overhead at real evidence size.
                "max_tokens": 8000,
            },
        )
        response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    if not content.strip():
        # FOUND LIVE 2026-09-05: the local Ollama model occasionally returns
        # a real HTTP 200 with an empty completion (no error to catch, no
        # exception to raise on its own). Without this check that empty
        # string got written straight into a new RecommendationSnapshot row,
        # silently replacing a real, useful cached narrative with nothing -
        # /recommendations then serves "no narrative yet" even though a good
        # one existed a cycle ago. Raising here routes through the Celery
        # task's existing try/except+notify and, critically, means the
        # failed generate_recommendations run never calls db.add() at all -
        # the last good snapshot stays live instead of being overwritten by
        # a worse one.
        raise RuntimeError("LLM returned an empty narrative")
    return content
