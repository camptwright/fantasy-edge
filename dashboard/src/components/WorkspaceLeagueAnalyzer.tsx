import { pts, type Overview } from "@/lib/workspace";

const tone = (rank: number, teams: number) => rank <= Math.ceil(teams / 3) ? "bg-emerald-400" : rank <= Math.ceil(2 * teams / 3) ? "bg-sky-400" : "bg-rose-400";
const ord = (n: number) => `${n}${["th", "st", "nd", "rd"][(n % 100 - 20) % 10] ?? ["th", "st", "nd", "rd"][n % 100] ?? "th"}`;

/** League Analyzer-style team rankings plus starter-slot and bench ranks (engine ROS research). */
export function WorkspaceLeagueAnalyzer({ overview }: { overview: Overview }) {
  const s = overview.strength;
  if (s.status !== "research" || !s.team_rankings.length) return null;
  return <section aria-label="League analyzer" className="grid gap-4 lg:grid-cols-2">
    <div className="rounded-xl border border-slate-800 p-4">
      <h2 className="font-semibold">Team rankings <span className="text-xs font-normal text-slate-500">· best ROS starting lineup, 100 = league best</span></h2>
      <ol className="mt-3 space-y-1.5 text-sm">{s.team_rankings.map(t => <li key={t.roster_id} className={`flex items-center gap-2 rounded-md px-2 py-1 ${t.is_mine ? "bg-emerald-500/10" : ""}`}>
        <span className="w-5 text-right text-[11px] tabular-nums text-slate-500">{t.rank}</span>
        <span className="min-w-0 flex-1 truncate">{t.name ?? t.roster_id}{t.is_mine && <span className="ml-2 text-[10px] uppercase tracking-wider text-emerald-300">You</span>}</span>
        <span aria-hidden="true" className="h-1.5 w-24 rounded bg-slate-800"><span className={`block h-1.5 rounded ${tone(t.rank, s.team_rankings.length)}`} style={{ width: `${t.score}%` }} /></span>
        <span className="w-10 text-right tabular-nums">{t.score.toFixed(0)}</span>
      </li>)}</ol>
    </div>
    <div className="rounded-xl border border-slate-800 p-4">
      <h2 className="font-semibold">Your starters by slot</h2>
      <ul className="mt-3 space-y-1.5 text-sm">{s.slots.map(slot => <li key={slot.slot} className="flex items-center gap-2">
        <span className="w-12 text-[11px] font-semibold text-slate-400">{slot.slot}</span>
        <span className="min-w-0 flex-1 truncate text-slate-300">{slot.player_name ?? (slot.slot === "BENCH" ? "Top bench players" : "—")}</span>
        <span className="text-[11px] tabular-nums text-slate-500">{pts(slot.value)}</span>
        {slot.rank != null && <><span aria-hidden="true" className="h-1.5 w-16 rounded bg-slate-800"><span className={`block h-1.5 rounded ${tone(slot.rank, slot.teams)}`} style={{ width: `${100 * (slot.teams - slot.rank + 1) / Math.max(1, slot.teams)}%` }} /></span>
          <span className="w-10 text-right text-xs tabular-nums">{ord(slot.rank)}</span></>}
      </li>)}</ul>
      <p className="mt-2 text-[11px] text-slate-500">Ranks among {s.teams || s.team_rankings.length} teams by each slot of their best rest-of-season lineup; bench is the top bench players’ total.</p>
    </div>
  </section>;
}
