"""Engine-based player-prop probabilities (research).

P(over) for receptions / receiving yards / rushing yards from the projection
engine's mean for that game and an empirical distribution of actual/projected
ratios (2025 walk-forward, by projection tercile), stored in
config/prop_engine_distribution.json by scripts/research_prop_model.py.

Evidence (same 2026 props): this beat the serving history-mean model on all
three stats but was worse than the no-vig market on all three, so it is shown
as a research comparison and never makes a prop actionable.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

CONFIG = Path(__file__).resolve().parents[2] / "config" / "prop_engine_distribution.json"
STATS = ("receptions", "receiving_yards", "rushing_yards")


@lru_cache(maxsize=1)
def load() -> dict | None:
    return json.loads(CONFIG.read_text()) if CONFIG.exists() else None


def over_probability(stat: str, mean: float, line: float, artifact: dict | None = None) -> float | None:
    artifact = artifact or load()
    spec = (artifact or {}).get("stats", {}).get(stat)
    if spec is None or mean is None or mean <= 0:
        return None
    edges, buckets = spec["edges"], spec["quantiles"]
    q = np.array(buckets[0 if mean < edges[0] else 1 if mean < edges[1] else 2])
    # Ratio quantiles define an empirical CDF; P(ratio * mean > line).
    levels = np.linspace(0, 1, len(q))
    return float(1 - np.interp(line / mean, q, levels, left=0.0, right=1.0))


def engine_stats(checkpoint: dict | None) -> dict[tuple[str, str], dict]:
    """(canonical player id, game id) -> projected stats from the engine research checkpoint."""
    out = {}
    for pid, weeks in ((checkpoint or {}).get("players") or {}).items():
        for entry in weeks.values():
            out[(pid, entry["game_id"])] = entry["stats"]
    return out
