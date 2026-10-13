"""Store evidence reports as deltas: only rows that changed, plus the row order.

Grading (and similar) reports were written in full every run although ~98%
of their rows repeat (measured 2026-10-13: 805 of 823 grading rows). A delta
keeps the report's small top-level fields whole, and for each large list
field stores the order of content-addressed row ids plus only the rows the
previous report did not have. `apply` rebuilds the exact report and verifies
it against the recorded digest, so history stays reconstructable and
tamper-evident: replay from the nearest full keyframe forward.
"""

from __future__ import annotations

import hashlib
import json

SCHEMA = "evidence_delta_v1"


def digest(payload) -> str:
    """Same canonical form as forecast_evidence.digest."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def row_id(row) -> str:
    return digest(row)[:24]


def delta(previous: dict | None, current: dict, list_fields: tuple[str, ...]) -> dict:
    lists = {}
    for field in list_fields:
        if field not in current:
            continue
        rows = current[field]
        ids = [row_id(r) for r in rows]
        known = {row_id(r) for r in (previous or {}).get(field) or []}
        lists[field] = {"order": ids, "added": {i: r for i, r in zip(ids, rows) if i not in known}}
    return {"schema": SCHEMA, "base_digest": digest(previous) if previous is not None else None,
            "digest": digest(current), "meta": {k: v for k, v in current.items() if k not in lists}, "lists": lists}


def apply(previous: dict | None, change: dict) -> dict:
    """Rebuild the full report from its base and a delta; raises if either does not verify."""
    if change.get("schema") != SCHEMA:
        raise ValueError("not an evidence delta")
    if change["base_digest"] is not None and (previous is None or digest(previous) != change["base_digest"]):
        raise ValueError("delta base does not match the previous report")
    full = dict(change["meta"])
    for field, spec in change["lists"].items():
        pool = {row_id(r): r for r in (previous or {}).get(field) or []}
        pool.update(spec["added"])
        full[field] = [pool[i] for i in spec["order"]]
    if digest(full) != change["digest"]:
        raise ValueError("rebuilt report does not match its recorded digest")
    return full


def replay(keyframe: dict, changes: list[dict]) -> dict:
    """A keyframe (full report) followed by the deltas recorded after it, oldest first."""
    full = keyframe
    for change in changes:
        full = apply(full, change)
    return full
