"""ORM row -> JSON-safe dict. FastAPI's jsonable_encoder already handles
UUID/datetime individually, but every router needs "give me this row's
columns as a dict" and SQLAlchemy models don't expose that natively -
`__dict__` carries SQLAlchemy's internal `_sa_instance_state` alongside the
real columns, which isn't JSON-serialisable and shouldn't be in a response
anyway.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import DeclarativeBase


def row_to_dict(row: DeclarativeBase, *, exclude: set[str] = frozenset()) -> dict[str, Any]:
    mapper = row.__mapper__
    return {
        col.key: getattr(row, col.key)
        for col in mapper.column_attrs
        if col.key not in exclude
    }
