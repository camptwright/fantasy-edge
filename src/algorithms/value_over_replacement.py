"""Season-long start/sit and waiver rankings via value over replacement.

VOR asks a different question than raw projected points: not "who scores
the most" but "who scores the most *more than a player freely available at
the same position*". A 20-point-per-game center is much easier to replace
off waivers than a 20-point-per-game point guard if centers are deep and
point guards are scarce - VOR is what surfaces that a positional scarcity
mismatch matters as much as raw talent for a season-long roster decision.
"""

from __future__ import annotations

from dataclasses import dataclass

# Replacement rank: the Nth-best player at a position is treated as "always
# available on waivers" in a standard league. 12-team leagues typically
# start 1 QB / 2 RB / 2-3 WR / 1 TE, so the replacement level sits a bit
# below the last starter across the league - these are standard
# season-long-fantasy defaults, overridable per league size.
DEFAULT_REPLACEMENT_RANK = {
    "QB": 12,
    "RB": 30,
    "WR": 36,
    "TE": 12,
    "DST": 12,
    "PG": 12,
    "SG": 12,
    "SF": 12,
    "PF": 12,
    "C": 12,
}


@dataclass
class PlayerValue:
    player_id: str
    name: str
    position: str
    projected_points: float


@dataclass
class VorResult:
    player_id: str
    name: str
    position: str
    projected_points: float
    replacement_level: float
    vor: float
    position_rank: int


def calculate_vor(
    players: list[PlayerValue],
    *,
    replacement_ranks: dict[str, int] | None = None,
) -> list[VorResult]:
    """One VOR result per player, sorted by VOR descending (the same order
    a start/sit or waiver-priority list should render in).
    """
    ranks = replacement_ranks or DEFAULT_REPLACEMENT_RANK

    by_position: dict[str, list[PlayerValue]] = {}
    for p in players:
        by_position.setdefault(p.position, []).append(p)

    replacement_level_by_position: dict[str, float] = {}
    position_rank_by_id: dict[str, int] = {}
    for position, group in by_position.items():
        sorted_group = sorted(group, key=lambda p: p.projected_points, reverse=True)
        for i, p in enumerate(sorted_group, start=1):
            position_rank_by_id[p.player_id] = i

        replacement_rank = ranks.get(position, 24)
        if replacement_rank <= len(sorted_group):
            replacement_level = sorted_group[replacement_rank - 1].projected_points
        elif sorted_group:
            # Fewer players at this position than the replacement rank
            # implies (e.g. a thin DST/TE pool) - fall back to the worst
            # available rather than crashing or inventing a value.
            replacement_level = sorted_group[-1].projected_points
        else:
            replacement_level = 0.0
        replacement_level_by_position[position] = replacement_level

    results = [
        VorResult(
            player_id=p.player_id,
            name=p.name,
            position=p.position,
            projected_points=p.projected_points,
            replacement_level=replacement_level_by_position[p.position],
            vor=p.projected_points - replacement_level_by_position[p.position],
            position_rank=position_rank_by_id[p.player_id],
        )
        for p in players
    ]
    results.sort(key=lambda r: r.vor, reverse=True)
    return results


def waiver_targets(
    rostered_ids: set[str], vor_results: list[VorResult], *, limit: int = 20
) -> list[VorResult]:
    """VOR-ranked players not already on a roster - the waiver wire."""
    available = [r for r in vor_results if r.player_id not in rostered_ids]
    return available[:limit]


def start_sit_recommendation(
    roster: list[VorResult], *, starters_by_position: dict[str, int]
) -> dict[str, list[VorResult]]:
    """Splits a roster into {"start": [...], "sit": [...]} per the league's
    starting slot counts, ranking within each position by VOR."""
    by_position: dict[str, list[VorResult]] = {}
    for r in roster:
        by_position.setdefault(r.position, []).append(r)

    start: list[VorResult] = []
    sit: list[VorResult] = []
    for position, group in by_position.items():
        sorted_group = sorted(group, key=lambda r: r.vor, reverse=True)
        n_starters = starters_by_position.get(position, 1)
        start.extend(sorted_group[:n_starters])
        sit.extend(sorted_group[n_starters:])

    start.sort(key=lambda r: r.vor, reverse=True)
    sit.sort(key=lambda r: r.vor, reverse=True)
    return {"start": start, "sit": sit}
