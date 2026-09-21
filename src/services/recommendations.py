"""Deterministic, quote-bound numeric summaries. No LLM or external calls."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    return max(
        (row.get(k) for k in ("edge_percent", "under_edge_percent") if row.get(k) is not None),
        default=float("-inf"),
    )


NARRATIVE_VERSION = "Deterministic quote summary (v1)"
NO_DATA_NARRATIVE = (
    "No positive-EV, actionable quotes with valid model probabilities are available."
)


def _priced(probability, price):
    from src.services.roster_stat_model import finite
    from src.utils.odds_math import american_to_implied, expected_value_percent

    if not finite(probability) or not 0 < probability < 1 or not finite(price) or abs(price) < 100:
        return None
    ev = expected_value_percent(probability, price)
    return (probability, price, american_to_implied(price), ev) if ev > 0 else None


def _label(value):
    # Provider text is a label, never executable instructions or multi-line prose.
    return " ".join(str(value or "").split())[:180]


def quote_summary(row, kind):
    if row.get("actionable") is not True or not row.get("id"):
        return None
    if kind == "signal":
        priced = _priced(row.get("model_probability"), row.get("price_american"))
        label = f"{_label(row.get('matchup'))}: {_label(row.get('selection'))}"
        book = row.get("bookmaker")
    else:
        from src.services.roster_stat_model import finite

        if not finite(row.get("line")):
            return None
        choices = []
        for side, key in (("Over", "model_probability"), ("Under", "under_model_probability")):
            value = _priced(row.get(key), row.get(side.lower() + "_price_american"))
            if value:
                choices.append((value[3], side, value))
        if not choices:
            return None
        _, side, priced = max(choices, key=lambda x: (x[0], x[1]))
        label = f"{_label(row.get('player_name'))}: {side} {row['line']:g} {_label(row.get('stat_type'))}"
        book = row.get("source")
    if priced is None:
        return None
    probability, price, implied, ev = priced
    model_pct, implied_pct = round(100 * probability, 2), round(100 * implied, 2)
    comparison = (
        "above"
        if model_pct > implied_pct
        else "below"
        if model_pct < implied_pct
        else "approximately equal to"
    )
    text = (
        f"{_label(row.get('sport')).upper()} · {label} · {_label(book)} {price:+g}. "
        f"Model probability {model_pct:.2f}% is {comparison} the price-implied "
        f"break-even probability {implied_pct:.2f}%. Estimated EV {ev:+.2f}% per unit staked."
    )
    return {"id": row["id"], "text": text, "ev": ev}


async def generate_narrative(db: AsyncSession, *, with_evidence=False):
    summaries = []
    for kind, rows in (
        ("signal", await signal_rows(db, sport=None)),
        ("prop", await prop_rows(db, sport=None, live_only=True)),
    ):
        summaries.extend(s for row in rows if (s := quote_summary(row, kind)) is not None)
    summaries = sorted(summaries, key=lambda s: (-s["ev"], s["id"]))[:_TOP_N]
    content = (
        (
            NARRATIVE_VERSION
            + "\n\n"
            + "\n\n".join(s["text"] for s in summaries)
            + "\n\nModel estimates are not guarantees. Price-implied probability includes bookmaker margin; "
            "EV is a percentage of stake, not American odds. No wager is placed."
        )
        if summaries
        else NO_DATA_NARRATIVE
    )
    return (
        {"narrative": content, "quote_ids": [s["id"] for s in summaries]}
        if with_evidence
        else content
    )


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

    if snapshot.narrative != NO_DATA_NARRATIVE and not snapshot.narrative.startswith(
        NARRATIVE_VERSION + "\n\n"
    ):
        return {
            "narrative": None,
            "generated_at": snapshot.generated_at.isoformat(),
            "note": "Legacy non-deterministic narrative withheld; refresh pending.",
        }

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
            return {
                "narrative": None,
                "generated_at": snapshot.generated_at.isoformat(),
                "note": "Invalid quote evidence.",
            }
        if len(ids) > 200:
            return {
                "narrative": None,
                "generated_at": snapshot.generated_at.isoformat(),
                "note": "Quote evidence exceeds validation limit.",
            }

        summaries = []
        for kind, rows in (
            ("signal", await signal_rows(db, None, quote_ids=ids)),
            ("prop", await prop_rows(db, None, live_only=True, quote_ids=ids)),
        ):
            summaries.extend(s for row in rows if (s := quote_summary(row, kind)) is not None)
        current = {s["id"] for s in summaries if s["text"] in snapshot.narrative}
        if not set(snapshot.quote_ids).issubset(current):
            return {
                "narrative": None,
                "generated_at": snapshot.generated_at.isoformat(),
                "note": "Underlying offers changed or are no longer actionable; refresh pending.",
            }

    return {"narrative": snapshot.narrative, "generated_at": snapshot.generated_at.isoformat()}
