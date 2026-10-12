/** Context is URL-owned and allowlisted; never forward arbitrary query parameters. */
export const WORKSPACES = [
  { id: "today", label: "Today" }, { id: "fantasy", label: "Fantasy" },
  { id: "markets", label: "Markets" }, { id: "research", label: "Research" },
  { id: "settings", label: "Settings" },
] as const;
export type Workspace = typeof WORKSPACES[number]["id"];
export function workspaceView(value?: string): Workspace {
  return WORKSPACES.find(view => view.id === value)?.id ?? "today";
}
export function workspaceHref(view: Workspace, league?: string): string {
  const query = new URLSearchParams({ view });
  if (league) query.set("league", league);
  return `/workspace?${query}`;
}
export function fantasyHref(path: string, league?: string): string {
  return league ? `${path}?${new URLSearchParams({ league })}` : path;
}
export const FANTASY_TOOLS = [
  {id: 'overview', label: 'Overview'}, {id: 'team', label: 'My team'},
  {id: 'waivers', label: 'Waivers'}, {id: 'players', label: 'Players'},
  {id: 'trade', label: 'Trade analyzer'},
] as const;
export type FantasyTool = typeof FANTASY_TOOLS[number]['id'];
export function fantasyTool(value?: string): FantasyTool {
  return FANTASY_TOOLS.find(tool => tool.id === value)?.id ?? 'overview';
}
export function fantasyToolHref(tool: FantasyTool, league?: string): string {
  return `${workspaceHref('fantasy', league)}&${new URLSearchParams({tool})}`;
}
export function playerResearchHref(league: string, player: string, compare?: string): string {
  const query = new URLSearchParams({player});
  if (compare && compare !== player) query.set('compare',compare);
  return `${fantasyToolHref('players',league)}&${query}`;
}
export function researchSelection(players: {player_id:string}[], player?:string, compare?:string) {
  const left = players.some(p=>p.player_id===player) ? player! : '';
  const right = left && compare !== left && players.some(p=>p.player_id===compare) ? compare! : '';
  return {left,right,unavailable:!!((player && !left) || (compare && !right))};
}
export function dailyReview(overview: Overview): {title: string; detail: string; tool: FantasyTool; attention: boolean}[] {
  if (overview.status !== 'snapshot_available') return [];
  const unknown = overview.roster_players.filter(p => p.points == null).length;
  const designations = overview.roster_players.filter(p => p.injury_status?.trim()
    && !['ACTIVE', 'HEALTHY'].includes(p.injury_status.trim().toUpperCase())).length;
  const rows: ReturnType<typeof dailyReview> = [];
  if (!overview.roster_players.length) rows.push({title: 'Roster evidence unavailable', detail: 'No uniquely bound roster in this snapshot. This is not an empty team.', tool: 'team', attention: true});
  if (designations) rows.push({title: `${designations} player designation${designations === 1 ? '' : 's'} to review`, detail: 'Check the supplied platform designations before setting your lineup. Missing designations do not confirm availability.', tool: 'team', attention: true});
  if (unknown) rows.push({title: `${unknown} unpriced roster player${unknown === 1 ? '' : 's'}`, detail: 'Unknown points are not zero. Review identity, scoring and history coverage.', tool: 'team', attention: true});
  const changes = overview.lineup_changes;
  rows.push({title: changes.status === 'available' && changes.start.length ? `${changes.start.length} candidate lineup change${changes.start.length === 1 ? '' : 's'}` : 'Review your lineup', detail: changes.reason, tool: 'team', attention: false});
  rows.push({title: overview.waivers.moves.length ? `${overview.waivers.moves.length} waiver alternative${overview.waivers.moves.length === 1 ? '' : 's'} to compare` : 'Explore waiver coverage', detail: 'Each add/drop is an alternative, not a combined plan. Check platform availability and waiver rules.', tool: 'waivers', attention: false});
  return rows;
}
export function snapshotRemainingMs(expiresAt: string | null, now: number): number {
  const deadline = expiresAt ? Date.parse(expiresAt) : NaN;
  return Number.isFinite(deadline) ? Math.max(0, deadline - now) : 0;
}

export type { LeagueSummary as League, Overview } from "./workspace-api.generated";

import type { Overview } from "./workspace-api.generated";
import type { PlayerDetail } from "./workspace-api.generated";
export function tradePackageOwner(players: PlayerDetail[], ids: string[]): string | null {
  if (!ids.length || new Set(ids).size !== ids.length) return null;
  const entries = ids.map(id => players.find(p => p.player_id === id));
  const owner = entries[0]?.roster_id;
  return owner && entries.every(p => p && ['your_roster','other_roster'].includes(p.ownership) && p.roster_id === owner) ? owner : null;
}
export function tradeCandidates(players: PlayerDetail[], ids: string[], other: string[], search: string, roster: string): PlayerDetail[] {
  const owner = tradePackageOwner(players, ids), opposite = tradePackageOwner(players, other);
  if ((ids.length && !owner) || (other.length && !opposite) || (owner && owner === opposite)) return [];
  const query = search.trim().toLowerCase();
  return players.filter(p => p.roster_id && ['your_roster','other_roster'].includes(p.ownership)
    && !ids.includes(p.player_id) && !other.includes(p.player_id)
    && p.roster_id !== opposite && (!owner || p.roster_id === owner)
    && (roster === 'all' || p.roster_id === roster)
    && `${p.name} ${p.position ?? ''} ${p.team ?? ''} ${p.roster_names.join(' ')}`.toLowerCase().includes(query))
    .sort((a,b) => a.name.localeCompare(b.name));
}
export type ResearchContext = Pick<Overview, 'league_id' | 'generated_at' | 'comparison_players'>;
export function researchContext(overview: Overview): ResearchContext {
  return {league_id: overview.league_id, generated_at: overview.generated_at,
    comparison_players: overview.comparison_players};
}

export function comparisonMatches(player: { name: string; position: string | null; team: string | null; ownership: string }, search: string, ownership: string): boolean {
  return (ownership === "all" || player.ownership === ownership)
    && `${player.name} ${player.position ?? ""} ${player.team ?? ""}`.toLowerCase().includes(search.trim().toLowerCase());
}

export function tradeBlockerText(code: string): string {
  const messages: Record<string, string> = {
    snapshot_changed_refresh_before_comparing: "The background snapshot changed. Refresh the evidence, review your selections, then evaluate again.",
    incomplete_roster_or_availability: "At least one supporting roster player lacks complete valuation evidence or needs an availability review. See the team details below.",
    incomplete_traded_player_values: "One or more traded players lack complete identity, scoring, history, or schedule evidence.",
    traded_player_availability_requires_review: "A traded player has a platform availability designation that needs review. The model does not infer recovery.",
    uneven_trade_requires_explicit_add_drop_plan: "Balance both roster sizes with explicit additions and drops. Each side’s net roster change must be zero.",
    packages_must_belong_to_two_distinct_rosters: "Each package must belong to one roster, and the two rosters must be different.",
    adjustment_player_locked_or_game_binding_unknown: "An addition or drop is locked, or its kickoff/game binding is unknown. Review the adjustment plan.",
    stale_inputs: "The saved inputs are stale. Refresh to check for newer evidence; do not treat this as a zero-value result.",
    uncorroborated_roster_ownership: "The saved player and roster records do not agree on ownership. Review the source roster before proceeding.",
    unknown_or_duplicate_player: "A trade player is missing from the checkpoint or appears more than once.",
    unknown_duplicate_or_excess_adjustment: "Adjustment plans contain an unknown, repeated, overlapping, or excess player. Use at most twelve unique adjustment players total.",
    add_not_corroborated_unrostered: "An addition is not confirmed unrostered in this checkpoint.",
    drop_not_corroborated_rostered: "A drop does not have corroborated roster ownership.",
    drop_not_owned_a: "Side A can only drop players from its own roster.",
    drop_not_owned_b: "Side B can only drop players from its own roster.",
  };
  return messages[code] ?? `Comparison withheld: ${code.replaceAll("_", " ")}.`;
}
export function availabilityLabel(status?: string): string {
  switch(status) {
    case 'team_unit_not_individual_injury_status': return 'Team defense: individual injury status does not apply; unit availability is not verified';
    case 'no_restriction_reported_not_game_clearance': return 'No restriction reported; not game-specific clearance';
    case 'reported_restriction_requires_review': return 'Reported restriction — review before lineup or trade decisions';
    default: return 'Not supplied — availability unconfirmed';
  }
}
