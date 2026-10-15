import { OVERVIEW_DEFAULTS, PLAYER_DEFAULTS, type Overview, type PlayerDetail } from './workspace-api.generated';
function defaults(base: unknown, value: unknown): unknown {
  if (base && value && typeof base==='object' && typeof value==='object' && !Array.isArray(base) && !Array.isArray(value)) {
    const result={...base,...value} as Record<string,unknown>;
    for (const [key,field] of Object.entries(value)) result[key]=defaults((base as Record<string,unknown>)[key],field);
    return result;
  }
  return value;
}
export function hydratePlayer(row: Partial<PlayerDetail>): PlayerDetail {
  return defaults(PLAYER_DEFAULTS,row) as PlayerDetail;
}
export function hydrateOverview(row: Overview | null): Overview | null {
  if (!row) return null;
  const result=defaults(OVERVIEW_DEFAULTS,row) as Overview;
  result.comparison_players=(row.comparison_players ?? []).map(hydratePlayer);
  result.roster_players=(row.roster_players ?? []).map(hydratePlayer);
  return result;
}
