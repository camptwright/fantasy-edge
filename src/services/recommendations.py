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

import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from src.api.routers.sportsbook import prop_rows, signal_rows

_TOP_N = 8
# How long a cached narrative stays servable before GET /recommendations
# (and get_valid_narrative below) treat it as expired and start returning
# "refresh pending" instead - matched to generate_recommendations' own
# 30-minute beat_schedule cadence in src/scheduler/celery_app.py, with the
# same 2700s (45 min) grace window /recommendations already used before
# this was pulled out into a shared constant.
_NARRATIVE_MAX_AGE_SECONDS = 2700


def prop_edge(row):
    return max((row.get(k) for k in ('edge_percent', 'under_edge_percent')
                if row.get(k) is not None), default=float('-inf'))

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


async def generate_narrative(db: AsyncSession, *, with_evidence=False):
    settings = get_settings()
    if not settings.litellm_api_key:
        raise RuntimeError("LITELLM_API_KEY is not configured")

    signals = sorted(
        (row for row in await signal_rows(db, sport=None) if row.get('actionable') and row["price_american"] is not None),
        key=lambda row: row["ev_percent"],
        reverse=True,
    )[:_TOP_N]
    props = sorted(
        (row for row in await prop_rows(db, sport=None, live_only=True)
         if row.get('actionable') and prop_edge(row) != float('-inf')),
        key=prop_edge,
        reverse=True,
    )[:_TOP_N]

    if not signals and not props:
        # Nothing to narrate yet - skip the ~78s round trip entirely rather
        # than asking the model to comment on empty evidence.
        return {'narrative': NO_DATA_NARRATIVE, 'quote_ids': []} if with_evidence else NO_DATA_NARRATIVE

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
                "under_edge_percent": row.get("under_edge_percent"),
                "over_price_american": row.get("over_price_american"),
                "under_price_american": row.get("under_price_american"),
                "source": row.get("source"),
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
    return {'narrative': content, 'quote_ids': [r['id'] for r in signals+props]} if with_evidence else content


async def get_valid_narrative(db: AsyncSession) -> dict:
    """The latest RecommendationSnapshot, gated the same way GET
    /recommendations always has: expired past _NARRATIVE_MAX_AGE_SECONDS,
    or its quote evidence no longer a subset of what's currently actionable
    (offers moved on), both come back as narrative=None with an explanatory
    note rather than serving stale/invalidated commentary.

    Pulled out of src/api/routers/sportsbook.py's `recommendations` route so
    a second consumer (src/scheduler/tasks.py's
    post_narrative_to_dashboard) can't drift from what a live API caller
    sees - there was exactly one copy of this gate before, now there's
    still exactly one, just reachable from two call sites.

    The import below is deliberately deferred, not module-level: this
    module already imports prop_rows/signal_rows FROM
    src.api.routers.sportsbook at the top of the file, so a module-level
    import in the other direction would make the two modules import each
    other during initial load - Python only tolerates that if every name
    needed is already bound by the time it's imported, which is fragile.
    Deferring until this function actually runs (never at import time)
    sidesteps it entirely.
    """
    from src.models.governance import RecommendationSnapshot

    snapshot = await db.scalar(
        select(RecommendationSnapshot).order_by(desc(RecommendationSnapshot.generated_at)).limit(1)
    )
    if snapshot is None:
        return {"narrative": None, "generated_at": None, "note": "no recommendation generated yet"}

    age = (datetime.now(timezone.utc) - snapshot.generated_at).total_seconds()
    if snapshot.quote_ids is None or not 0 <= age <= _NARRATIVE_MAX_AGE_SECONDS:
        return {
            "narrative": None,
            "generated_at": snapshot.generated_at.isoformat(),
            "note": "Narrative expired or lacks verifiable quote evidence; refresh pending.",
        }

    # Mirrors the original route's "if snapshot.quote_ids:" guard exactly -
    # an empty (not None - see the check above) quote_ids list means
    # NO_DATA_NARRATIVE, which trivially has no evidence to re-verify, so
    # skip the two extra queries below rather than running them against an
    # empty id set for no reason.
    if snapshot.quote_ids:
        try:
            ids = {uuid.UUID(value) for value in snapshot.quote_ids}
        except (ValueError, TypeError, AttributeError):
            return {"narrative": None, "generated_at": snapshot.generated_at.isoformat(), "note": "Invalid quote evidence."}
        if len(ids) > 200:
            return {
                "narrative": None,
                "generated_at": snapshot.generated_at.isoformat(),
                "note": "Quote evidence exceeds validation limit.",
            }

        current = {
            r["id"]
            for r in (await signal_rows(db, None, quote_ids=ids)) + (await prop_rows(db, None, live_only=True, quote_ids=ids))
            if r.get("actionable")
        }
        if not set(snapshot.quote_ids).issubset(current):
            return {
                "narrative": None,
                "generated_at": snapshot.generated_at.isoformat(),
                "note": "Underlying offers changed or are no longer actionable; refresh pending.",
            }

    return {"narrative": snapshot.narrative, "generated_at": snapshot.generated_at.isoformat()}
