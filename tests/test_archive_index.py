"""The archive file-signature index is one updatable row, not an append-only copy per run."""

import json

from sqlalchemy import func, select

from src.models.governance import DerivedCheckpoint, ForecastArchive
from src.services import forecast_evidence as fe


async def test_repeated_imports_keep_a_single_index_row(db, tmp_path):
    for i in range(3):
        (tmp_path / f"20261001T00000{i}.json").write_text(json.dumps({"forecast": i}))
    first = await fe.import_archives(db, tmp_path, kind="forecasts")
    (tmp_path / "20261001T000009.json").write_text(json.dumps({"forecast": 9}))
    second = await fe.import_archives(db, tmp_path, kind="forecasts")
    assert (first["imported"], second["imported"]) == (3, 1)
    copies = await db.scalar(select(func.count()).select_from(ForecastArchive).where(ForecastArchive.kind == "archive_index"))
    assert copies == 0
    row = await db.get(DerivedCheckpoint, fe.index_name(tmp_path, "forecasts"))
    assert len(row.payload["files"]) == 4 and row.digest == fe.digest(row.payload)
    third = await fe.import_archives(db, tmp_path, kind="forecasts")
    assert third["imported"] == 0  # unchanged files are skipped via the cached signatures
