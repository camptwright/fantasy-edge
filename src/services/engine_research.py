"""Reader for the engine research checkpoint (written by projection_engine_serving).

Kept free of engine imports so the fantasy snapshot builder can read it
under projection_identity's versioned-dependency rule. The checkpoint
carries its own `engine_version`. v1's values are research only; v2's
(V2_NAME, projection_engine_v2_serving) feed decisions as half of a blend.
"""

from src.models.governance import DerivedCheckpoint

NAME = "projection_engine:research"
V2_NAME = "projection_engine_v2:serving"


async def latest(db, name=NAME):
    row = await db.get(DerivedCheckpoint, name)
    return row.payload if row else None


def player_points(entry, weights):
    return round(sum(entry["stats"].get(stat, 0.0) * w for stat, w in weights.items()), 2)
