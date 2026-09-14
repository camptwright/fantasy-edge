type Stat = { stat: string; status: string; games: number; baseline?: number; candidate?: number;
  historical_low?: number; historical_high?: number; last_result?: string; method?: string;
  evaluation?: { games: number; baseline_mae: number | null; candidate_mae: number | null } };
export type PlayerLabData = { status: string; reason?: string; league_id?: string; league_name?: string;
  prospective?: { status: string; generated_at?: string; total_forecasts?: number; counts?: Record<string, number>;
    metrics: { version: string; stat: string; n: number; baseline_mae: number; candidate_mae: number }[] };
  roster_synced_at?: string; leagues: { id: string; name: string }[]; notes?: string[];
  players: { roster_player_id: string; name: string; position: string; team: string; starter: boolean;
    injury_status: string; status: string; opponent: string | null; game_time: string | null; stats: Stat[] }[] };
const label = (s: string) => s.replaceAll("_", " ");
const number = (n?: number | null) => n == null ? "—" : n.toFixed(1);
export function NflPlayerLab({ data }: { data: PlayerLabData }) {
  return <section id="player-lab" className="mb-10 space-y-4">
    <h2 className="text-2xl font-semibold text-slate-100">NFL Player Stat Lab</h2>
    <p className="text-sm text-slate-400">Your Fantasy roster · full-game estimates conditional on playing · experimental, not live in-game projections</p>
    <details className="rounded-lg border border-cyan-900 p-3 text-sm text-slate-300"><summary>Prospective testing · {data.prospective?.total_forecasts || 0} frozen forecasts · {data.prospective?.counts?.graded || 0} graded</summary>
      <p className="my-2">Across all owned leagues, deduplicated by player/game/stat/model. First eligible capture 5 minutes–72 hours before kickoff; checked every 15 minutes. Forecasts stay unchanged; grades follow corrected finals. Missing stats are not zero.</p>
      <p>Last evaluation: {data.prospective?.generated_at || "Not started"}. {Object.entries(data.prospective?.counts || {}).map(([k,v])=>`${label(k)}: ${v}`).join(" · ")}</p>
      {!data.prospective?.metrics.length && <p>No graded evidence yet. The candidate has not earned promotion.</p>}
      {data.prospective?.metrics.map(m=><p key={`${m.version}:${m.stat}`}>{label(m.stat)} · model {m.version.slice(0,8)} · {m.n} results · MAE baseline {number(m.baseline_mae)} / candidate {number(m.candidate_mae)}</p>)}
    </details>
    <nav aria-label="Fantasy league" className="flex flex-wrap gap-2">{data.leagues.map(l => <a key={l.id}
      href={`/experimental?league=${encodeURIComponent(l.id)}#player-lab`} aria-current={data.league_id === l.id ? "page" : undefined}
      className={`rounded-lg border px-3 py-2 text-sm ${data.league_id === l.id ? "border-cyan-600 text-cyan-200" : "border-slate-700 text-slate-400"}`}>{l.name}</a>)}</nav>
    {data.status !== "experimental" ? <p role="alert" className="text-amber-200">Player lab unavailable: {label(data.reason || "API unavailable")}. No projections are fabricated.</p> : <>
      <p className="text-xs text-slate-400">Roster synced: {data.roster_synced_at ? new Date(data.roster_synced_at).toUTCString() : "unknown"}. Baseline: last 20 recorded games (minimum 8). Candidate: conservative recent-opportunity blend where usage history exists. Lower backtest MAE is better; it is not proof of future accuracy.</p>
      <div className="space-y-4">{[...data.players].sort((a,b) => Number(b.starter)-Number(a.starter)).map(p => <article key={p.roster_player_id} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="font-semibold text-slate-100">{p.name} <span className="text-sm font-normal text-slate-400">{p.position} · {p.team || "team unknown"} · {p.starter ? "Starter" : "Bench"}</span></h3><span className="text-xs text-amber-200">Roster injury label: {p.injury_status} (unverified)</span></div>
        <p className="my-2 text-xs text-slate-400">{p.game_time ? `Next: ${p.opponent} · ${new Date(p.game_time).toUTCString()}` : "No upcoming scheduled game found in the next 10 days; estimates are historical only."}</p>
        {p.status !== "ready" && <p className="text-sm text-amber-200">{label(p.status)}{p.status === "unsupported_position" ? " — kickers and defenses are outside this first version." : " — estimates require an exact player ID and at least 8 recorded games."}</p>}
        {p.stats.length > 0 && <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-xs text-slate-400"><tr>{["Stat", "Baseline", "Candidate", "Historical range", "Games", "Backtest MAE (base / candidate)"].map(h=><th key={h} className="py-2 pr-4">{h}</th>)}</tr></thead><tbody>{p.stats.map(s=><tr key={s.stat} className="border-t border-slate-800 text-slate-200"><td className="py-2 pr-4 capitalize">{label(s.stat)}</td>{s.status === "ready" ? <><td>{number(s.baseline)}</td><td>{number(s.candidate)}<span className="block text-xs text-slate-500">{s.method === "baseline_only" ? "baseline only" : "usage blend"}</span></td><td>{number(s.historical_low)}–{number(s.historical_high)}</td><td>{s.games}</td><td>{number(s.evaluation?.baseline_mae)} / {number(s.evaluation?.candidate_mae)}<span className="block text-xs text-slate-500">{s.evaluation?.games || 0} past-only tests</span></td></> : <td colSpan={5} className="text-slate-400">{label(s.status)} ({s.games} games)</td>}</tr>)}</tbody></table></div>}
      </article>)}</div>
      <ul className="list-disc space-y-1 pl-5 text-xs text-slate-400">{data.notes?.map(n=><li key={n}>{n}</li>)}</ul>
    </>}
  </section>;
}
