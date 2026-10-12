"""Read raw-archive JSON whether or not retention has gzip-compressed it.

`src/services/raw_retention.compress_daily` losslessly replaces day-old
`<name>.json` files in append-only archive directories with `<name>.json.gz`
(hash-verified). Readers of those directories go through here so a file is
the same evidence in either form: `read_bytes` returns the original JSON
bytes, so content hashes of a report are unchanged by compression.

Create-only identity records (forecast captures keyed by id) are never
compressed: their first-observation-wins check depends on the exact path.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

GZ = ".gz"


def logical_name(path: Path) -> str:
    return path.name.removesuffix(GZ)


def files(directory: Path | str, pattern: str = "*.json") -> list[Path]:
    """Matches for `pattern` and `pattern.gz`, ordered by their uncompressed name."""
    directory = Path(directory)
    found = [*directory.glob(pattern), *directory.glob(pattern + GZ)]
    return sorted(found, key=logical_name)


def resolve(path: Path | str) -> Path:
    """The stored path, or its compressed replacement if retention ran."""
    path = Path(path)
    if not path.exists() and path.suffix != GZ:
        compressed = path.with_name(path.name + GZ)
        if compressed.exists():
            return compressed
    return path


def read_bytes(path: Path | str) -> bytes:
    path = resolve(path)
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == GZ else data


def read_json(path: Path | str) -> Any:
    return json.loads(read_bytes(path))
