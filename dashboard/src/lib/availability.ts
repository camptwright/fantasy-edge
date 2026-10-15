/** Provider status aliases. A missing restriction does not confirm game participation. */
export function normalizeStatus(value?: string | null): string | null {
  const key = (value ?? "").trim().toUpperCase().replaceAll(/[ -]/g, "_");
  const aliases: Record<string, string> = { Q: "QUESTIONABLE", D: "DOUBTFUL", O: "OUT",
    INJURY_RESERVE: "IR", INJURED_RESERVE: "IR", INJUREDRESERVE: "IR", SUS: "SUSPENDED",
    SUSPENSION: "SUSPENDED", PHYSICALLY_UNABLE_TO_PERFORM: "PUP", PUP_R: "PUP", PUP_P: "PUP",
    NON_FOOTBALL_INJURY: "NFI", NON_FOOTBALL_ILLNESS: "NFI", COVID_19: "COV", HEALTHY: "ACTIVE", NORMAL: "ACTIVE" };
  return aliases[key] ?? (key || null);
}
export const ABSENT_STATUSES = new Set(["OUT", "IR", "PUP", "SUSPENDED", "NFI", "NA", "COV", "DNR", "INACTIVE"]);
