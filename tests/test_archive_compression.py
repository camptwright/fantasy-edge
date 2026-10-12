"""Lossless daily archive compression and the gzip-aware readers."""

from __future__ import annotations

import gzip
import json
import os
import time
from collections import namedtuple
from datetime import timedelta

from src.services import raw_retention
from src.services.injury_evidence import archive_rows
from src.services.reconciliation import check_disk_space
from src.utils import archive_io


def _write(path, payload, age_days=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    old = time.time() - age_days * 86400
    os.utime(path, (old, old))
    return path


def test_readers_see_compressed_and_plain_files_in_timestamp_order(tmp_path):
    a = _write(tmp_path / "20261001T000000.json", {"n": 1})
    b = _write(tmp_path / "20261002T000000.json", {"n": 2})
    original = a.read_bytes()
    a.with_name(a.name + ".gz").write_bytes(gzip.compress(original))
    a.unlink()
    files = archive_io.files(tmp_path)
    assert [archive_io.logical_name(p) for p in files] == [a.name, b.name]
    assert archive_io.read_json(files[0]) == {"n": 1}
    # A stored pre-compression path still resolves, byte-identical.
    assert archive_io.read_bytes(a) == original


def test_daily_compression_is_lossless_bounded_and_allowlisted(tmp_path):
    old = _write(tmp_path / "grading" / "20261001T000000.json", {"report": "x" * 5000}, age_days=3)
    fresh = _write(tmp_path / "grading" / "20261012T000000.json", {"report": "new"}, age_days=0)
    identity = _write(tmp_path / "fantasy-prospective" / "forecasts" / "abc.json", {"id": "abc"}, age_days=9)
    nested = _write(tmp_path / "college-player-lab" / "sources" / "20261001T000000.json", {}, age_days=9)
    original = old.read_bytes()

    result = raw_retention.compress_daily(root=tmp_path, min_age=timedelta(days=1))

    assert result["compressed"] == 1 and result["deleted"] == 0
    assert not old.exists() and gzip.decompress(old.with_name(old.name + ".gz").read_bytes()) == original
    assert fresh.exists(), "files younger than a day stay plain"
    assert identity.exists(), "create-only identity records are never compressed"
    assert nested.exists(), "only direct files of an allowlisted directory"


def test_compression_respects_the_byte_budget(tmp_path):
    for day in (1, 2, 3):
        _write(tmp_path / "forecasts" / f"2026100{day}T000000.json", {"x": "y" * 1000}, age_days=10 - day)
    result = raw_retention.compress_daily(root=tmp_path, max_bytes=1500)
    assert result["compressed"] == 1 and result["remaining_files"] == 2


def test_existing_latest_reader_reads_a_compressed_archive(tmp_path):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    path = _write(tmp_path / "20261001T000000.json", {"rows": [{"observed_at": now, "reported_at": now}]})
    path.with_name(path.name + ".gz").write_bytes(gzip.compress(path.read_bytes()))
    path.unlink()
    rows, state = archive_rows(tmp_path, datetime.now(timezone.utc))
    assert state == "fresh_archive" and len(rows) == 1


def test_disk_alert_fires_at_eighty_percent(monkeypatch):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("src.services.reconciliation.shutil.disk_usage",
                        lambda path: usage(100e9, 85e9, 15e9))
    issues = check_disk_space("/unused")
    assert issues and issues[0].check == "disk_space" and "85%" in issues[0].detail
    monkeypatch.setattr("src.services.reconciliation.shutil.disk_usage",
                        lambda path: usage(100e9, 50e9, 50e9))
    assert check_disk_space("/unused") == []
