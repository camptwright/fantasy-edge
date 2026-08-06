"""backfill Team identity onto the canonical (ESPN name/espn_id) rows

Constraint #24: historical seeding used to create Team rows keyed on
whatever raw identifier its loader produced ("KC"), with no espn_id set,
while live ESPN sync never created a row of its own (read-only lookup) -
so there was only ever one row per team, just under the wrong name. Now
that `src/data/team_resolution.py` resolves through
`config/team_aliases/<sport>.yaml` to a canonical ESPN name/espn_id, any
row still sitting under the old raw name needs to become that canonical
row - and if a canonical row also happens to already exist (defensive
case, not expected given the above), every Game/PowerRanking/Player FK
pointing at the old row is re-pointed onto the canonical one before the
old row is dropped, per constraint #24's original repoint-then-delete
plan.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-06
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import sqlalchemy as sa
import yaml

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Alembic migrations should be self-contained against the schema as it
# existed at this point, not import a live app module that will keep
# changing - read the same YAML files `config/settings.get_team_aliases`
# reads at runtime directly, rather than importing config.settings.
ALIASES_DIR = Path(__file__).resolve().parents[2] / "config" / "team_aliases"


def _load_aliases(sport: str) -> dict[str, dict[str, str]]:
    path = ALIASES_DIR / f"{sport}.yaml"
    if not path.exists():
        return {}
    with path.open() as fh:
        raw = yaml.safe_load(fh) or {}
    return raw.get("aliases", {})


def _repoint_and_drop(conn: sa.Connection, old_id: Any, canonical_id: Any) -> None:
    conn.execute(
        sa.text("UPDATE games SET home_team_id = :new WHERE home_team_id = :old"),
        {"new": canonical_id, "old": old_id},
    )
    conn.execute(
        sa.text("UPDATE games SET away_team_id = :new WHERE away_team_id = :old"),
        {"new": canonical_id, "old": old_id},
    )
    conn.execute(
        sa.text("UPDATE power_rankings SET team_id = :new WHERE team_id = :old"),
        {"new": canonical_id, "old": old_id},
    )
    conn.execute(
        sa.text("UPDATE players SET team_id = :new WHERE team_id = :old"),
        {"new": canonical_id, "old": old_id},
    )
    conn.execute(sa.text("DELETE FROM teams WHERE id = :old"), {"old": old_id})


def upgrade() -> None:
    conn = op.get_bind()

    for sport in ("nfl", "mlb", "nhl"):
        for raw_name, alias in _load_aliases(sport).items():
            espn_name = alias["espn_name"]
            espn_id = alias["espn_id"]

            old_row = conn.execute(
                sa.text("SELECT id FROM teams WHERE sport = :sport AND name = :name"),
                {"sport": sport, "name": raw_name},
            ).first()
            canonical_row = conn.execute(
                sa.text(
                    "SELECT id FROM teams WHERE sport = :sport "
                    "AND (name = :espn_name OR espn_id = :espn_id)"
                ),
                {"sport": sport, "espn_name": espn_name, "espn_id": espn_id},
            ).first()

            if old_row is None:
                continue  # nothing seeded under the raw name yet - fine

            if canonical_row is not None and canonical_row[0] != old_row[0]:
                # Genuine duplicate: repoint every FK off the old row onto
                # the canonical one, then drop the now-orphaned old row.
                _repoint_and_drop(conn, old_row[0], canonical_row[0])
            else:
                # No duplicate - the old row IS the only row for this team.
                # Rename it in place so it becomes canonical; every FK
                # already pointing at its id stays correct automatically.
                conn.execute(
                    sa.text(
                        "UPDATE teams SET name = :espn_name, espn_id = :espn_id "
                        "WHERE id = :id"
                    ),
                    {"espn_name": espn_name, "espn_id": espn_id, "id": old_row[0]},
                )


def downgrade() -> None:
    # Not meaningfully reversible: the old raw-name identifiers ("KC") are
    # not recoverable from the canonical rows alone once merged, and
    # un-repointing FKs would require knowing which old row each one used
    # to point at, which no longer exists to check.
    raise NotImplementedError(
        "0002_backfill_team_identity is a one-way data migration - restore "
        "from a pre-migration backup instead of downgrading."
    )
