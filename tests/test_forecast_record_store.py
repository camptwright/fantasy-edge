"""Content-addressed capture records: identical selection to full captures, a fraction of the storage."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from src.models.governance import ForecastArchive
from src.services import forecast_evidence as fe
from src.services.forecast_checkpoint import load, refresh
from src.services.forecast_grading import cohort_from_payloads


def capture(gid, at, quotes, p=0.6):
    return {"schema_version": 1, "captured_at": at.isoformat(), "model_version": "v1", "records": [
        {"kind": "team", "game_id": gid, "market": "moneyline", "side": "home", "quote_id": q,
         "prediction": {"model_probability": p, "sport": "nfl", "last_seen_at": at.isoformat()},
         "inputs": {"padding": list(range(50))}} for q in quotes]}


def test_compact_round_trip_restores_every_record_exactly():
    now = datetime.now(timezone.utc)
    full = capture(str(uuid4()), now, ["a", "b"])
    full["records"].append({"kind": "player", "game_id": "g", "market": "receptions", "side": "over"})  # no prediction
    compact, bodies = fe.compact_capture(full)
    assert compact["records"][0].keys() == {"$body", "last_seen_at"} and "last_seen_at" not in compact["records"][2]
    assert fe.expand_records(compact, bodies) == full
    bodies[compact["records"][0]["$body"]]["prediction"]["model_probability"] = 0.9
    with pytest.raises(ValueError, match="altered"):
        fe.expand_records(compact, bodies)


async def test_repeated_captures_store_each_body_once_and_select_identically(db):
    gid, now = str(uuid4()), datetime.now(timezone.utc)
    captures = [capture(gid, now + timedelta(minutes=15 * i), ["a", "b", "c"]) for i in range(4)]
    captures.append(capture(gid, now + timedelta(hours=1, minutes=15), ["a", "b", "c"], p=0.65))  # model changed
    for c in captures:
        await fe.save_capture(db, c)
    await db.commit()
    counts = dict((await db.execute(select(ForecastArchive.kind, func.count()).group_by(ForecastArchive.kind))).all())
    assert counts == {"forecasts": 5, "forecast_record": 6}  # 3 bodies, then 3 new ones after the change
    await db.commit()
    await refresh(db)
    await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
    state, _ = await load(db)
    from src.services.forecast_checkpoint import pack
    assert pack(state) == pack(cohort_from_payloads(captures, True))  # same selection as full captures
    streamed = [p async for p in fe.payloads(db, "forecasts")]
    assert sorted(p["captured_at"] for p in streamed) == sorted(c["captured_at"] for c in captures)
    assert all("record_encoding" not in p and "$body" not in p["records"][0] for p in streamed)
