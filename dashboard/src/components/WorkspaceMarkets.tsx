import { fantasyApi } from "@/lib/fantasy-api";

type Signal = {
  id: string; sport: string; market: string; selection: string; bookmaker: string; price_american: number | null;
  model_probability: number | null; fair_probability: number | null; ev_percent: number | null; actionable: boolean;
  exclusion_reason: string | null; matchup: string | null; game_time: string | null;
};
type TeamProjections = { status: string; sport?: string; model_version?: string; ratings: { team: string; name?: string | null; rating: number; offense?: number | null; defense?: number | null }[];
  games: { game_id: string; home: string; away: string; game_time: string; model_margin: number; market_margin: number | null; margin: number; home_win_probability: number; market_weight: number | null;
    total?: number; market_total?: number | null; model_total?: number; home_points?: number; away_points?: number; home_name?: string | null; away_name?: string | null }[];
  evidence?: { test_seasons: number[]; model_brier: number; previous_elo_brier: number; market_brier: number; regressed_brier: number } };
type Ledger = { scope: string; items: unknown[]; event_count: number; exposure: Record<string, unknown> };

const pctText = (v: number | null) => v == null ? "—" : `${(v * 100).toFixed(1)}%`;
const price = (v: number | null) => v == null ? "—" : v > 0 ? `+${v}` : `${v}`;
const when = (iso: string | null) => iso ? new Date(iso).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit", timeZone: "America/Chicago" }) : "Time TBD";

/** Native market summary in the workspace shell; the full tools stay one click away. */
export async function WorkspaceMarkets() {
  const [nfl, ncaaf, ledger, brief, teams] = await Promise.all([
    fantasyApi<Signal[]>("/signals?sport=nfl", 5000), fantasyApi<Signal[]>("/signals?sport=ncaaf", 5000),
    fantasyApi<Ledger>("/api/v1/ledger", 5000), fantasyApi<{ narrative: string; generated_at: string }>("/recommendations", 5000),
    fantasyApi<TeamProjections>("/team-projections/nfl", 5000)]);
  const college = await fantasyApi<TeamProjections>("/team-projections/ncaaf", 5000);
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
    <GameProjections data={teams} />
    <a href="/workspace?view=props" className="block rounded-xl border border-slate-800 bg-slate-900/60 p-4 hover:border-emerald-500/60"><span className="font-semibold">Player props and parlay generator →</span><span className="mt-1 block text-sm text-slate-400">Every book&apos;s prop prices against a no-vig consensus, with hit rates and matchups.</span></a>
    {college?.status === "research" && <GameProjections data={college} />}
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

const line = (home: string, away: string, margin: number | null) => margin == null ? "—" : Math.abs(margin) < 0.25 ? "Pick" : margin > 0 ? `${home} −${margin.toFixed(1)}` : `${away} −${(-margin).toFixed(1)}`;

/** NFL team model v2: projected lines for the coming week and power ratings. */
export function GameProjections({ data }: { data: TeamProjections | null }) {
  if (!data || data.status !== "research") return <p role="status" className="rounded-xl border border-slate-800 p-4 text-sm text-slate-400">Team projections unavailable. This is a service error, not an empty slate.</p>;
  const ev = data.evidence;
  const college = data.sport === "ncaaf";
  const short = (name?: string | null, code?: string) => college ? (name ?? code ?? "?") : (code ?? "?");
  return <section aria-label="Game projections" className="grid gap-4 lg:grid-cols-[1fr_16rem]">
    <div>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <h2 className="text-lg font-semibold">{college ? "College football" : "NFL"} game projections <span className="ml-1 rounded bg-sky-500/15 px-2 py-0.5 align-middle text-[11px] font-medium uppercase tracking-wider text-sky-300">{college ? "College team model" : "Team model v2"}</span></h2>
      </div>
      {!data.games.length ? <p className="rounded-xl border border-slate-800 p-4 text-sm text-slate-400">No NFL games in the next 8 days.</p> :
      <div className="workspace-scrollbar overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full min-w-[48rem] text-sm">
          <thead className="bg-slate-900/70 text-xs text-slate-400"><tr>{["Game", "Model", "Market", "Projection", "Total", "Team points", "Home win"].map((h, i) => <th key={h} scope="col" className={`px-3 py-2 font-medium ${i ? "text-right" : "text-left"}`}>{h}</th>)}</tr></thead>
          <tbody>{data.games.map(g => { const [h, a] = [short(g.home_name, g.home), short(g.away_name, g.away)]; return <tr key={g.game_id} className="border-t border-slate-800/70">
            <td className="px-3 py-2">{a} @ {h}<span className="block text-[11px] text-slate-500">{when(g.game_time)}</span></td>
            <td className="px-3 py-2 text-right tabular-nums text-slate-300">{line(h, a, g.model_margin)}</td>
            <td className="px-3 py-2 text-right tabular-nums text-slate-400">{line(h, a, g.market_margin)}</td>
            <td className="px-3 py-2 text-right font-medium tabular-nums">{line(h, a, g.margin)}{g.market_weight != null && g.market_weight < 1 && <span className="block text-[11px] font-normal text-sky-300">model keeps {Math.round((1 - g.market_weight) * 100)}% of its view</span>}</td>
            <td className="px-3 py-2 text-right tabular-nums">{g.total != null ? g.total.toFixed(1) : "—"}{g.model_total != null && g.market_total != null && <span className="block text-[11px] text-slate-500">model {g.model_total.toFixed(1)}</span>}</td>
            <td className="px-3 py-2 text-right tabular-nums">{g.home_points != null && g.away_points != null ? `${a} ${g.away_points.toFixed(1)} · ${h} ${g.home_points.toFixed(1)}` : "—"}</td>
            <td className="px-3 py-2 text-right tabular-nums">{pctText(g.home_win_probability)}</td>
          </tr>; })}</tbody>
        </table>
      </div>}
      {ev && <p className="mt-2 text-xs text-slate-500">{college ? "Program-anchored ratings (the SP+/FPI preseason practice) on FiveThirtyEight/nfelo updates; neutral-site games are not flagged yet, so home field applies to every game." : "Rebuilt from FiveThirtyEight’s and nfelo’s published methods."} On {ev.test_seasons[0]}–{ev.test_seasons[1]} games it never saw, Brier {ev.model_brier.toFixed(4)} vs {ev.previous_elo_brier.toFixed(4)} for the previous Elo; the closing market ({ev.market_brier.toFixed(4)}) is still better, so projections lean on the market unless the model strongly disagrees.</p>}
    </div>
    <div className="rounded-xl border border-slate-800 p-4">
      <h3 className="text-sm font-semibold">{college ? "Top 25" : "Power ratings"} <span className="font-normal text-slate-500">· pts vs average</span></h3>
      <ol className="mt-2 space-y-1 text-sm">{data.ratings.slice(0, college ? 25 : 32).map((r, i) => <li key={r.team} className="flex items-center gap-2">
        <span className="w-5 text-right text-[11px] tabular-nums text-slate-500">{i + 1}</span><span className={college ? "w-36 truncate" : "w-10"} title={r.name ?? undefined}>{college ? short(r.name, r.team) : r.team}</span>
        <span aria-hidden="true" className="relative h-1.5 flex-1 rounded bg-slate-800"><span className={`absolute top-0 h-1.5 rounded ${r.rating >= 0 ? "left-1/2 bg-emerald-400" : "right-1/2 bg-rose-400"}`} style={{ width: `${Math.min(50, Math.abs(r.rating) * 4)}%` }} /></span>
        <span className="w-12 text-right tabular-nums text-slate-300" title={r.offense != null && r.defense != null ? `Offense ${r.offense.toFixed(1)} · defense ${r.defense.toFixed(1)}` : undefined}>{r.rating > 0 ? "+" : ""}{r.rating.toFixed(1)}</span></li>)}</ol>
      <p className="mt-2 text-[11px] text-slate-500">Margin rating; hover for the offense/defense scoring split.</p>
    </div>
  </section>;
}
