"""Reader for the engine research checkpoint (written by projection_engine_serving).

Kept free of engine imports so the fantasy snapshot builder can read it
under projection_identity's versioned-dependency rule. The checkpoint
carries its own `engine_version`; the values are research, never decisions.
"""

from src.models.governance import DerivedCheckpoint

NAME = "projection_engine:research"


async def latest(db):
    row = await db.get(DerivedCheckpoint, NAME)
    return row.payload if row else None


def player_points(entry, weights):
    return round(sum(entry["stats"].get(stat, 0.0) * w for stat, w in weights.items()), 2)
