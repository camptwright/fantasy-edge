"""DFS lineup optimization: a linear program solved with PuLP.

The model assigns PLAYERS TO SLOTS (a binary variable per player-slot pair),
not just "select N players" - that distinction matters as soon as a roster
has a FLEX/UTIL slot with overlapping eligibility (a FLEX can be a RB, WR, or
TE; a UTIL can be anything). A simpler "pick 9 players satisfying position
counts" formulation either double-counts a player across two slots or needs
ad-hoc tie-breaking to decide which slot a multi-eligible player "uses" -
the assignment formulation sidesteps that by making slot occupancy an
explicit decision the solver makes jointly with player selection, which is
also what makes it a correct linear program rather than a heuristic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pulp


@dataclass
class RosterSlot:
    name: str
    eligible_positions: frozenset[str]


@dataclass
class SiteRules:
    site: str  # draftkings | fanduel
    salary_cap: int
    roster_slots: list[RosterSlot]
    max_players_per_team: int | None = None


@dataclass
class PlayerCandidate:
    player_id: str
    name: str
    team: str
    positions: frozenset[str]
    salary: int
    projected_points: float


@dataclass
class LineupSlotAssignment:
    slot_name: str
    player_id: str
    name: str
    salary: int
    projected_points: float


@dataclass
class LineupResult:
    feasible: bool
    total_salary: int
    total_projected_points: float
    assignments: list[LineupSlotAssignment] = field(default_factory=list)


# ------------------------------------------------------------- site rules ----
# DraftKings and FanDuel classic contest rules for the two sports with the
# clearest, most stable slot structures. Other sports follow the same
# `SiteRules` shape and can be added the same way once needed - this is a
# data addition, not a code change to the optimizer itself.

_FLEX_NBA = frozenset({"PG", "SG", "SF", "PF", "C"})

DK_NBA = SiteRules(
    site="draftkings",
    salary_cap=50_000,
    roster_slots=[
        RosterSlot("PG", frozenset({"PG"})),
        RosterSlot("SG", frozenset({"SG"})),
        RosterSlot("SF", frozenset({"SF"})),
        RosterSlot("PF", frozenset({"PF"})),
        RosterSlot("C", frozenset({"C"})),
        RosterSlot("G", frozenset({"PG", "SG"})),
        RosterSlot("F", frozenset({"SF", "PF"})),
        RosterSlot("UTIL", _FLEX_NBA),
    ],
)

FD_NBA = SiteRules(
    site="fanduel",
    salary_cap=60_000,
    roster_slots=[
        RosterSlot("PG", frozenset({"PG"})),
        RosterSlot("PG2", frozenset({"PG"})),
        RosterSlot("SG", frozenset({"SG"})),
        RosterSlot("SG2", frozenset({"SG"})),
        RosterSlot("SF", frozenset({"SF"})),
        RosterSlot("SF2", frozenset({"SF"})),
        RosterSlot("PF", frozenset({"PF"})),
        RosterSlot("PF2", frozenset({"PF"})),
        RosterSlot("C", frozenset({"C"})),
    ],
    max_players_per_team=4,
)

_FLEX_NFL = frozenset({"RB", "WR", "TE"})

DK_NFL = SiteRules(
    site="draftkings",
    salary_cap=50_000,
    roster_slots=[
        RosterSlot("QB", frozenset({"QB"})),
        RosterSlot("RB1", frozenset({"RB"})),
        RosterSlot("RB2", frozenset({"RB"})),
        RosterSlot("WR1", frozenset({"WR"})),
        RosterSlot("WR2", frozenset({"WR"})),
        RosterSlot("WR3", frozenset({"WR"})),
        RosterSlot("TE", frozenset({"TE"})),
        RosterSlot("FLEX", _FLEX_NFL),
        RosterSlot("DST", frozenset({"DST"})),
    ],
)

FD_NFL = SiteRules(
    site="fanduel",
    salary_cap=60_000,
    roster_slots=[
        RosterSlot("QB", frozenset({"QB"})),
        RosterSlot("RB1", frozenset({"RB"})),
        RosterSlot("RB2", frozenset({"RB"})),
        RosterSlot("WR1", frozenset({"WR"})),
        RosterSlot("WR2", frozenset({"WR"})),
        RosterSlot("WR3", frozenset({"WR"})),
        RosterSlot("TE", frozenset({"TE"})),
        RosterSlot("FLEX", _FLEX_NFL),
        RosterSlot("DST", frozenset({"DST"})),
    ],
    max_players_per_team=4,
)

SITE_RULES: dict[tuple[str, str], SiteRules] = {
    ("draftkings", "nba"): DK_NBA,
    ("fanduel", "nba"): FD_NBA,
    ("draftkings", "wnba"): DK_NBA,  # same slot shape, different player pool
    ("fanduel", "wnba"): FD_NBA,
    ("draftkings", "nfl"): DK_NFL,
    ("fanduel", "nfl"): FD_NFL,
}


def get_site_rules(site: str, sport: str) -> SiteRules:
    key = (site, sport)
    if key not in SITE_RULES:
        raise KeyError(f"no DFS roster rules configured for site={site} sport={sport}")
    return SITE_RULES[key]


# -------------------------------------------------------------- optimizer ----


def optimize_lineup(
    players: list[PlayerCandidate],
    rules: SiteRules,
    *,
    locked_player_ids: frozenset[str] = frozenset(),
    excluded_player_ids: frozenset[str] = frozenset(),
) -> LineupResult:
    """Solves for the salary-cap-feasible lineup maximising total projected
    points. CBC (PuLP's bundled solver) finds the true optimum for a problem
    this size in well under a second - there's no need for a heuristic.
    """
    candidates = [p for p in players if p.player_id not in excluded_player_ids]
    players_by_id = {p.player_id: p for p in candidates}

    problem = pulp.LpProblem("dfs_lineup", pulp.LpMaximize)

    # x[(player_id, slot_name)] = 1 if that player fills that slot.
    assign_vars: dict[tuple[str, str], pulp.LpVariable] = {}
    for player in candidates:
        for slot in rules.roster_slots:
            if player.positions & slot.eligible_positions:
                var = pulp.LpVariable(f"x_{player.player_id}_{slot.name}", cat="Binary")
                assign_vars[(player.player_id, slot.name)] = var

    if not assign_vars:
        return LineupResult(feasible=False, total_salary=0, total_projected_points=0.0)

    problem += pulp.lpSum(
        players_by_id[pid].projected_points * var
        for (pid, _slot), var in assign_vars.items()
    )

    # Each slot filled by exactly one eligible player.
    for slot in rules.roster_slots:
        slot_vars = [
            var for (pid, sname), var in assign_vars.items() if sname == slot.name
        ]
        if slot_vars:
            problem += pulp.lpSum(slot_vars) == 1

    # Each player used in at most one slot.
    by_player: dict[str, list[pulp.LpVariable]] = {}
    for (pid, _slot), var in assign_vars.items():
        by_player.setdefault(pid, []).append(var)
    for pid, var_list in by_player.items():
        problem += pulp.lpSum(var_list) <= 1
        if pid in locked_player_ids:
            problem += pulp.lpSum(var_list) == 1

    salary_by_id = {p.player_id: p.salary for p in candidates}
    problem += (
        pulp.lpSum(salary_by_id[pid] * var for (pid, _slot), var in assign_vars.items())
        <= rules.salary_cap
    )

    if rules.max_players_per_team is not None:
        teams = {p.team for p in candidates}
        for team in teams:
            team_vars = [
                var
                for (pid, _slot), var in assign_vars.items()
                if players_by_id[pid].team == team
            ]
            if team_vars:
                problem += pulp.lpSum(team_vars) <= rules.max_players_per_team

    status = problem.solve(pulp.PULP_CBC_CMD(msg=False))

    if pulp.LpStatus[status] != "Optimal":
        return LineupResult(feasible=False, total_salary=0, total_projected_points=0.0)

    assignments: list[LineupSlotAssignment] = []
    for (pid, slot_name), var in assign_vars.items():
        if var.value() and var.value() > 0.5:
            player = players_by_id[pid]
            assignments.append(
                LineupSlotAssignment(
                    slot_name=slot_name,
                    player_id=pid,
                    name=player.name,
                    salary=player.salary,
                    projected_points=player.projected_points,
                )
            )

    # Sort assignments in roster_slots order for a stable, readable lineup
    # display rather than dict-iteration order.
    slot_order = {slot.name: i for i, slot in enumerate(rules.roster_slots)}
    assignments.sort(key=lambda a: slot_order[a.slot_name])

    return LineupResult(
        feasible=True,
        total_salary=sum(a.salary for a in assignments),
        total_projected_points=sum(a.projected_points for a in assignments),
        assignments=assignments,
    )
