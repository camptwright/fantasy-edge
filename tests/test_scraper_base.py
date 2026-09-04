"""BaseScraper's raw-archive and pacing primitives.

Network fetch itself (curl_cffi TLS impersonation against a real endpoint)
is exercised by each concrete scraper's own `live`-marked test, not here -
this covers only the two things every subclass gets for free.
"""

from __future__ import annotations

import gzip
import time
from types import SimpleNamespace
from unittest.mock import patch

from src.data.scrapers.base import BaseScraper


class _FakeScraper(BaseScraper):
    source = "fake_source"
    min_interval = 0.05


async def test_archive_writes_gzipped_content_under_source_and_date(tmp_path):
    scraper = _FakeScraper()
    fake_settings = SimpleNamespace(raw_archive_dir=str(tmp_path))
    with patch("src.data.scrapers.base.get_settings", return_value=fake_settings):
        await scraper._archive("https://example.com/odds", b'{"ok": true}')

    files = list((tmp_path / "fake_source").glob("*/*.json.gz"))
    assert len(files) == 1
    assert gzip.decompress(files[0].read_bytes()) == b'{"ok": true}'


async def test_archive_hashes_url_into_the_filename_for_traceability(tmp_path):
    scraper = _FakeScraper()
    fake_settings = SimpleNamespace(raw_archive_dir=str(tmp_path))
    with patch("src.data.scrapers.base.get_settings", return_value=fake_settings):
        await scraper._archive("https://example.com/one", b"a")
        await scraper._archive("https://example.com/two", b"b")

    files = sorted((tmp_path / "fake_source").glob("*/*.json.gz"))
    assert len(files) == 2
    # Different URLs must not collide on the same archive filename.
    assert files[0].name != files[1].name


async def test_throttle_paces_consecutive_calls_by_min_interval():
    scraper = _FakeScraper()
    start = time.monotonic()
    await scraper._throttle()
    await scraper._throttle()
    elapsed = time.monotonic() - start
    assert elapsed >= scraper.min_interval


async def test_throttle_does_not_wait_if_enough_time_already_passed():
    scraper = _FakeScraper()
    scraper._last_request = time.monotonic() - 10
    start = time.monotonic()
    await scraper._throttle()
    assert time.monotonic() - start < scraper.min_interval
