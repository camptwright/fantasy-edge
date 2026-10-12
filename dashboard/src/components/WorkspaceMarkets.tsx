import { fantasyApi } from "@/lib/fantasy-api";

type Signal = {
  id: string; sport: string; market: string; selection: string; bookmaker: string; price_american: number | null;
  model_probability: number | null; fair_probability: number | null; ev_percent: number | null; actionable: boolean;
  exclusion_reason: string | null; matchup: string | null; game_time: string | null;
};
type Ledger = { scope: string; items: unknown[]; event_count: number; exposure: Record<string, unknown> };

const pctText = (v: number | null) => v == null ? "—" : `${(v * 100).toFixed(1)}%`;
const price = (v: number | null) => v == null ? "—" : v > 0 ? `+${v}` : `${v}`;
const when = (iso: string | null) => iso ? new Date(iso).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit", timeZone: "America/Chicago" }) : "Time TBD";

/** Native market summary in the workspace shell; the full tools stay one click away. */
export async function WorkspaceMarkets() {
  const [nfl, ncaaf, ledger, brief] = await Promise.all([
    fantasyApi<Signal[]>("/signals?sport=nfl", 5000), fantasyApi<Signal[]>("/signals?sport=ncaaf", 5000),
    fantasyApi<Ledger>("/api/v1/ledger", 5000), fantasyApi<{ narrative: string; generated_at: string }>("/recommendations", 5000)]);
  const unavailable = nfl === null && ncaaf === null;
  const signals = [...(nfl ?? []), ...(ncaaf ?? [])];
  const actionable = signals.filter(s => s.actionable);
  const upcoming = signals.filter(s => !s.game_time || Date.parse(s.game_time) > Date.now())
    .sort((a, b) => Number(b.actionable) - Number(a.actionable) || (b.ev_percent ?? -99) - (a.ev_percent ?? -99)).slice(0, 15);
  const reasons = Object.entries(signals.filter(s => !s.actionable).reduce<Record<string, number>>((acc, s) => {
    const key = s.exclusion_reason ?? "unspecified"; acc[key] = (acc[key] ?? 0) + 1; return acc; }, {})).sort((a, b) => b[1] - a[1]);
  return <div className="space-y-6">
    <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {([["Actionable signals", unavailable ? "—" : String(actionable.length), "Passed every eligibility gate"],
        ["Research signals", unavailable ? "—" : String(signals.length - actionable.length), "Shown for research; not bets"],
        ["Ledger bets", ledger ? String(ledger.items.length) : "—", ledger ? "Manual/paper singles" : "Ledger unavailable"],
        ["Ledger events", ledger ? String(ledger.event_count) : "—", "Recorded decisions and settlements"]] as const).map(([label, value, sub]) =>
        <div key={label} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4"><dt className="text-xs text-slate-400">{label}</dt><dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd><dd className="mt-1 text-[11px] text-slate-500">{sub}</dd></div>)}
    </dl>
    {brief?.narrative && <p className="rounded-xl border border-slate-800 p-4 text-sm text-slate-300"><span className="mr-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Briefing</span>{brief.narrative}</p>}
    <section aria-label="Market signals">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <h2 className="text-lg font-semibold">Upcoming signals</h2>
        <p className="text-xs text-slate-500">Actionable first, then by model EV · research rows are not betting instructions</p>
      </div>
      {unavailable ? <p role="status" className="rounded-xl border border-amber-800 p-4 text-sm">The signals service is unavailable. This is a connection error, not an empty board.</p>
        : !upcoming.length ? <p role="status" className="rounded-xl border border-slate-800 p-4 text-sm text-slate-400">No upcoming signals in the current snapshot.</p> :
      <div className="workspace-scrollbar overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full min-w-[44rem] text-sm">
          <thead className="bg-slate-900/70 text-xs text-slate-400"><tr>{["Game", "Selection", "Book · price", "Model", "No-vig market", "EV", "Status"].map((h, i) => <th key={h} scope="col" className={`px-3 py-2 font-medium ${i >= 3 && i <= 5 ? "text-right" : "text-left"}`}>{h}</th>)}</tr></thead>
          <tbody>{upcoming.map(s => <tr key={s.id} className="border-t border-slate-800/70">
            <td className="px-3 py-2"><span className="block">{s.matchup ?? "Unbound game"}</span><span className="text-[11px] text-slate-500">{s.sport.toUpperCase()} · {when(s.game_time)}</span></td>
            <td className="px-3 py-2">{s.selection}<span className="block text-[11px] text-slate-500">{s.market}</span></td>
            <td className="px-3 py-2 tabular-nums">{s.bookmaker} · {price(s.price_american)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{pctText(s.model_probability)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{pctText(s.fair_probability)}</td>
            <td className={`px-3 py-2 text-right tabular-nums ${s.actionable ? "text-emerald-300" : "text-slate-400"}`}>{s.ev_percent == null ? "—" : `${s.ev_percent.toFixed(1)}%`}</td>
            <td className="px-3 py-2">{s.actionable ? <span className="rounded-full bg-emerald-400 px-2 py-0.5 text-[11px] font-semibold text-slate-950">Actionable</span>
              : <span className="text-[11px] text-amber-200/80">Research · {(s.exclusion_reason ?? "unspecified").replaceAll("_", " ")}</span>}</td>
          </tr>)}</tbody>
        </table>
      </div>}
      {!!reasons.length && <p className="mt-2 text-xs text-slate-500">Why signals are not actionable: {reasons.slice(0, 4).map(([r, n]) => `${r.replaceAll("_", " ")} (${n})`).join(" · ")}. Large research EVs usually mean an unvalidated model disagrees with a sharp market, not an edge.</p>}
    </section>
  </div>;
}
