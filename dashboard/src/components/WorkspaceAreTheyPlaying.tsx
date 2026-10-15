import { playerProfileHref, type Overview } from "@/lib/workspace";
import type { PlayerDetail } from "@/lib/workspace-api.generated";
import { ABSENT_STATUSES, normalizeStatus } from "@/lib/availability";

type Verdict = { label: string; tone: "bad" | "warn" | "ok" | "done"; detail: string };
const TONE = { bad: "bg-rose-500/15 text-rose-200", warn: "bg-amber-500/15 text-amber-200", ok: "bg-emerald-500/15 text-emerald-200", done: "bg-slate-700 text-slate-300" };
const when = (iso?: string | null) => iso ? new Date(iso).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit", timeZone: "America/Chicago" }) : "kickoff unknown";

const PRACTICE: Record<string, string> = { dnp: "did not practice", limited: "limited practice", full: "full practice" };

/** "Plays 78% of the time" for a designated regular, from 2016-2025 injury reports; empty when not modelled. */
export function playOdds(p: PlayerDetail): string {
  if (p.play_probability == null) return "";
  const practice = p.practice_status ? `${PRACTICE[p.practice_status]} · ` : "";
  const status = normalizeStatus(p.injury_status) === "DOUBTFUL" ? "Doubtful" : "Questionable";
  return `${practice}regulars listed ${status} on the final report played ${Math.round(p.play_probability * 100)}%`;
}

/** One verdict per starter: platform designation, bye, game-linked report, game state. Evidence, not clearance. */
export function verdict(p: PlayerDetail): Verdict {
  const status = normalizeStatus(p.injury_status);
  if (p.week_game_status === "no_game_this_week") return { label: "Bye", tone: "bad", detail: "No game this week — start someone else." };
  if (status && ABSENT_STATUSES.has(status)) return { label: status === "IR" ? "IR" : "Out", tone: "bad", detail: `Platform designation ${p.injury_status}.` };
  if (p.game_availability_hold) return { label: "Review", tone: "warn", detail: "A game-linked injury report needs review; a historical designation rate is not game clearance." };
  const odds = playOdds(p);
  if (status === "DOUBTFUL" || status === "D") return { label: "Doubtful", tone: "bad", detail: `Unlikely to play${odds ? ` (${odds})` : ""}; have a replacement ready.` };
  if (status === "QUESTIONABLE" || status === "Q") return { label: odds ? `Q · ${Math.round((p.play_probability ?? 0) * 100)}%` : "Questionable", tone: "warn", detail: `${odds ? `${odds[0].toUpperCase()}${odds.slice(1)}. ` : ""}Check news before ${when(p.week_kickoff)}.` };
  if (p.week_game_status === "final") return { label: "Final", tone: "done", detail: "Game finished." };
  if (p.week_game_status === "in_progress" || p.locked) return { label: "Locked", tone: "done", detail: "Game started; lineup locked." };
  if (p.week_game_status === "scheduled" && status && status !== "ACTIVE") return {label:"Review",tone:"warn",detail:`Designation ${p.injury_status}; review the report before ${when(p.week_kickoff)}.`};
  if (p.week_game_status === "scheduled") return { label: "Scheduled", tone: "ok", detail: `${p.opponent ? `vs ${p.opponent} · ` : ""}${when(p.week_kickoff)} · no restriction reported; participation unconfirmed.` };
  return { label: "Unknown", tone: "warn", detail: "Game binding unknown; confirm on your platform." };
}

/** FantasyPros' "Are they playing?": problems first. */
export function WorkspaceAreTheyPlaying({ overview }: { overview: Overview }) {
  const byId = new Map(overview.roster_players.map(p => [p.player_id, p]));
  const starters = (overview.matchup.mine?.starters ?? []).flatMap(s => s.player_id && byId.get(s.player_id) ? [{ slot: s.slot, p: byId.get(s.player_id)! }] : []);
  if (!starters.length) return null;
  const rows = starters.map(s => ({ ...s, v: verdict(s.p) }));
  const rank = { bad: 0, warn: 1, ok: 2, done: 3 } as const;
  rows.sort((a, b) => rank[a.v.tone] - rank[b.v.tone]);
  const problems = rows.filter(r => r.v.tone === "bad").length;
  return <section aria-label="Are they playing" className="mt-6 rounded-2xl border border-slate-800 p-5">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="text-lg font-semibold">Are they playing?</h2>
      <p className={`text-xs ${problems ? "text-rose-300" : "text-slate-400"}`}>{problems ? `${problems} starter${problems === 1 ? "" : "s"} need a replacement plan` : "No reported absence among starters"}</p>
    </div>
    <ul className="mt-3 divide-y divide-slate-800">{rows.map(({ slot, p, v }) => <li key={p.player_id} className="flex items-center gap-3 py-2 text-sm">
      <span className="w-10 text-[11px] text-slate-500">{slot}</span>
      <a href={playerProfileHref(overview.league_id, p.player_id)} className="min-w-0 flex-1 truncate hover:underline">{p.name}<span className="ml-2 text-[11px] text-slate-500">{p.position} · {p.team ?? "FA"}</span></a>
      <span title={v.detail} className="hidden max-w-[45%] truncate text-xs text-slate-400 sm:inline">{v.detail}</span>
      <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${TONE[v.tone]}`}>{v.label}</span>
    </li>)}</ul>
    <details className="mt-2 text-xs text-slate-500"><summary className="cursor-pointer">Availability evidence</summary>
      <p className="mt-2">Scheduled means a game is linked; confirm final inactives before kickoff.</p>
      <ul className="mt-2 space-y-1">{rows.map(({p,v}) => { const evidence = p as PlayerDetail & {practice_observed_at?: string | null; practice_evidence_status?: string | null};
        return <li key={p.player_id}>{p.name}: {v.detail}{p.game_availability_observed_at ? ` Event report checked ${when(p.game_availability_observed_at)}.` : ""}
          {evidence.practice_observed_at ? ` Practice report dated ${when(evidence.practice_observed_at)}.` : ""}
          {evidence.practice_evidence_status && evidence.practice_evidence_status !== "matched_fresh_report" ? ` Practice unavailable: ${evidence.practice_evidence_status.replaceAll("_", " ")}.` : ""}</li>; })}</ul>
    </details>
  </section>;
}
