/** Shapes and pure helpers for the Props screen (prop board, tracker, parlay generator). */

export type Offer = { book: string; line: number; over: number | null; under: number | null; observed_at: string };
export type Rate = { hits: number; games: number } | null;
export type PropRow = {
  key: string; sport: string; game_id: string; game_time: string; matchup: string; player_id: string; player: string;
  position: string | null; team: string | null; opponent: string | null; stat: string; line: number; books: number; quoted: number;
  fair_over: number | null; spread: number | null; hold: number | null;
  best_over: { book: string; price: number } | null; best_under: { book: string; price: number } | null;
  ev_over: number | null; ev_under: number | null; other_lines: number[];
  hit: { l5: Rate; l10: Rate; season: Rate; vs_opponent: Rate; average_l10: number | null; last5: number[] };
  engine: { projection: number; over_probability: number; minutes?: number } | null; dvp: { rank: number; teams: number } | null;
  offers: Offer[]; last_seen: string; score: number;
};
export type TrackerSummary = { tracked: number; graded: number; wins: number; units: number; roi: number | null;
  expected_roi: number | null; average_clv: number | null; clv_n: number; beat_close: number | null };
export type PropBoard = { status: string; sport: string; generated_at?: string; books: string[]; stats: string[]; total: number;
  rows: PropRow[]; method?: string; tracker: TrackerSummary | null };

export type ParlayLeg = { id: string; book: string; price: number; fair: number; ev: number; side: "over" | "under"; line: number; stat: string;
  player: string; position: string | null; team: string | null; opponent: string | null; matchup: string; game_time: string; reasons: string[] };
export type Parlay = { book: string; legs: ParlayLeg[]; decimal: number; american: number; independent_probability: number; probability: number;
  fair_american: number | null; same_game: boolean; ev: number | null; score: number };
export type ParlayResult = { status: string; relaxed?: string; candidates?: number; books?: string[]; parlays: Parlay[]; note?: string;
  constraints: Record<string, unknown> | null; ai: { used: boolean; model?: string; ms?: number; note?: string } | null };

export const STAT_LABELS: Record<string, string> = {
  passing_yards: "Pass yds", passing_attempts: "Pass att", passing_completions: "Completions", passing_touchdowns: "Pass TD",
  passing_interceptions: "INT", rushing_yards: "Rush yds", rushing_attempts: "Carries", receptions: "Receptions", receiving_yards: "Rec yds",
};
export const statLabel = (s: string) => STAT_LABELS[s] ?? s.replaceAll("_", " ");
export const american = (v: number | null | undefined) => v == null ? "—" : v > 0 ? `+${v}` : `${v}`;
export const percent = (v: number | null | undefined, digits = 0) => v == null ? "—" : `${(v * 100).toFixed(digits)}%`;
export const signedPct = (v: number | null | undefined) => v == null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
export const rate = (r: Rate) => r && r.games ? `${r.hits}/${r.games}` : "—";
export const bookLabel = (b: string) => ({ draftkings: "DraftKings", fanduel: "FanDuel", betmgm: "BetMGM", caesars: "Caesars",
  espnbet: "ESPN BET", bovada: "Bovada", pinnacle: "Pinnacle" } as Record<string, string>)[b] ?? b;

/** The side with the better EV (or the over when neither is priced). */
export function bestSide(r: PropRow): "over" | "under" {
  return (r.ev_under ?? -9) > (r.ev_over ?? -9) ? "under" : "over";
}

/** Share of a hit-rate window that went the given side's way. */
export function sideRate(r: Rate, side: "over" | "under"): number | null {
  if (!r || !r.games) return null;
  return (side === "over" ? r.hits : r.games - r.hits) / r.games;
}

export type SortKey = "ev" | "l10" | "dvp" | "time";
export function sortRows(rows: PropRow[], key: SortKey): PropRow[] {
  const ev = (r: PropRow) => Math.max(r.ev_over ?? -9, r.ev_under ?? -9);
  const by: Record<SortKey, (r: PropRow) => number> = {
    ev: r => -ev(r),
    l10: r => -(sideRate(r.hit.l10, bestSide(r)) ?? -1),
    // Overs want soft defences (rank 1 allows the most); unders want stingy ones.
    dvp: r => r.dvp ? (bestSide(r) === "over" ? r.dvp.rank : r.dvp.teams + 1 - r.dvp.rank) : 99,
    time: r => Date.parse(r.game_time),
  };
  return [...rows].sort((a, b) => by[key](a) - by[key](b) || a.key.localeCompare(b.key));
}

export function filterRows(rows: PropRow[], f: { stat?: string; book?: string; q?: string; minEv?: number | null }): PropRow[] {
  const q = f.q?.trim().toLowerCase();
  return rows.filter(r => (!f.stat || r.stat === f.stat)
    && (!f.book || r.offers.some(o => o.book === f.book))
    && (!q || r.player.toLowerCase().includes(q) || r.matchup.toLowerCase().includes(q) || (r.team ?? "").toLowerCase() === q)
    && (f.minEv == null || Math.max(r.ev_over ?? -9, r.ev_under ?? -9) >= f.minEv));
}
