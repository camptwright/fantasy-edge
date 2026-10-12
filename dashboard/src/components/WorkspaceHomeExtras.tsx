import { fantasyToolHref, type Overview } from "@/lib/workspace";

const ACTIONS = [
  ["team", "Lineup", "M4 6h10M4 12h7M4 18h10M18 9l3 3-3 3"],
  ["startsit", "Start/Sit", "M7 4v16M17 4v16M3 8h8M13 16h8"],
  ["waivers", "Waivers", "M9 11a4 4 0 100-8 4 4 0 000 8zM3 21v-1a6 6 0 0112 0v1M19 8v6M16 11h6"],
  ["trade", "Trade", "M4 8h14l-3-3M20 16H6l3 3"],
] as const;

/** FantasyPros My Playbook-style quick actions. */
export function QuickActions({ overview }: { overview: Overview }) {
  return <nav aria-label="Quick actions" className="mt-6 grid grid-cols-4 gap-2 sm:gap-3">{ACTIONS.map(([tool, label, d]) =>
    <a key={tool} href={fantasyToolHref(tool, overview.league_id)} className="flex flex-col items-center gap-2 rounded-2xl border border-slate-800 bg-slate-900/60 py-4 text-xs font-medium text-slate-200 hover:border-emerald-500/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300 sm:text-sm">
      <svg aria-hidden="true" viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>{label}
    </a>)}</nav>;
}

const BAR = { QB: "bg-violet-400", RB: "bg-cyan-400", WR: "bg-emerald-400", TE: "bg-rose-400" } as Record<string, string>;
const ordinal = (n: number) => `${n}${["th", "st", "nd", "rd"][(n % 100 > 10 && n % 100 < 14) ? 0 : n % 10 < 4 ? n % 10 : 0]}`;

/** Power-rankings-style positional strength from engine ROS research. */
export function PositionStrength({ overview }: { overview: Overview }) {
  const s = overview.strength;
  if (s.status !== "research") return null;
  const ring = s.overall_rank != null && s.teams ? 1 - (s.overall_rank - 1) / Math.max(1, s.teams - 1) : 0;
  return <section aria-label="Positional strength" className="mt-8 rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
    <div className="flex flex-wrap items-end justify-between gap-2">
      <h2 className="text-lg font-semibold">League strength <span className="ml-1 rounded bg-sky-500/15 px-2 py-0.5 align-middle text-[11px] font-medium uppercase tracking-wider text-sky-300">Engine research</span></h2>
      <p className="text-xs text-slate-500">Best starters by position, rest-of-season engine points vs every roster</p>
    </div>
    <div className="mt-4 flex flex-wrap items-center gap-6">
      <div className="relative h-28 w-28 shrink-0" role="img" aria-label={s.overall_rank ? `Overall ${ordinal(s.overall_rank)} of ${s.teams}` : "Overall rank unavailable"}>
        <svg viewBox="0 0 36 36" className="h-28 w-28 -rotate-90"><circle cx="18" cy="18" r="15.5" fill="none" className="stroke-slate-700" strokeWidth="3" />
          <circle cx="18" cy="18" r="15.5" fill="none" className="stroke-emerald-400" strokeWidth="3" strokeLinecap="round" strokeDasharray={`${ring * 97.4} 97.4`} /></svg>
        <span className="absolute inset-0 grid place-items-center text-center"><span><span className="block text-3xl font-bold">{s.overall_rank ? ordinal(s.overall_rank) : "—"}</span><span className="text-[10px] text-slate-400">of {s.teams || "?"}</span></span></span>
      </div>
      <dl className="min-w-[14rem] flex-1 space-y-2">{s.positions.map(p => <div key={p.position} className="grid grid-cols-[2.5rem_1fr_3rem] items-center gap-3 text-sm">
        <dt className="font-medium text-slate-300">{p.position}</dt>
        <dd className="h-2 overflow-hidden rounded-full bg-slate-700"><div className={`h-full rounded-full ${BAR[p.position] ?? "bg-slate-400"}`} style={{ width: `${p.value != null && p.league_best ? (p.value / p.league_best) * 100 : 0}%` }} /></dd>
        <dd className="text-right tabular-nums text-slate-300">{p.rank ? ordinal(p.rank) : "—"}</dd>
      </div>)}</dl>
    </div>
    <p className="mt-3 text-xs text-slate-500">Ranks only rosters whose needed starters all have engine research; FLEX, K and DEF are not included. Research, not a validated power ranking.</p>
  </section>;
}
