import type { Overview } from "@/lib/workspace";
import { pct, playerProfileHref, pts } from "@/lib/workspace";
import type { MatchupSide, PlayerDetail } from "@/lib/workspace-api.generated";

const evidence = (source: string) => source === "estimated" ? "Provider"
  : source === "estimated_history" ? "History · if playing" : "Unpriced";

/** Engine research sum over offensive starters; partial coverage is reported, never filled. */
export function engineTotal(side: MatchupSide | null | undefined, players: Map<string, PlayerDetail>) {
  const offense = (side?.starters ?? []).filter(s => s.player_id && ["QB", "RB", "WR", "TE"].includes(players.get(s.player_id)?.position ?? ""));
  const values = offense.map(s => players.get(s.player_id!)?.engine_week_points).filter((v): v is number => v != null);
  return { total: values.length ? values.reduce((a, b) => a + b, 0) : null, covered: values.length, offense: offense.length };
}

/** Server-rendered scorecard from the checkpoint, with no extra API requests. */
export function WorkspaceMatchup({ overview }: { overview: Overview }) {
  const { matchup, lineup_changes: changes } = overview;
  const players = new Map(overview.comparison_players.map(p => [p.player_id, p]));
  const sides = (["mine", "opponent"] as const).map(key => ({ key, side: matchup[key], engine: engineTotal(matchup[key], players) }));
  return <section aria-label="Matchup snapshot" className="rounded-2xl border border-slate-800 bg-gradient-to-b from-slate-900 to-slate-950">
    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 p-5 md:p-6">
      {sides.map(({ key, side, engine }, i) => <div key={key} className={`min-w-0 ${i ? "order-3 text-right" : ""}`}>
        <p className={`truncate text-sm font-semibold ${key === "mine" ? "text-emerald-300" : "text-slate-300"}`}>{side?.name ?? (key === "mine" ? "Your roster unavailable" : "Opponent unavailable")}</p>
        <p className="mt-1 text-4xl font-bold tabular-nums tracking-tight md:text-5xl">{pts(side?.recorded_points)}</p>
        <p className="mt-1 text-xs text-slate-400">Recorded score</p>
        <dl className={`mt-3 space-y-1 text-xs ${i ? "ml-auto" : ""}`}>
          <div className={`flex gap-2 ${i ? "justify-end" : ""}`}><dt className="text-slate-500">Provider pregame</dt><dd className="tabular-nums text-slate-200">{pts(side?.pregame_points)}</dd></div>
          <div className={`flex gap-2 ${i ? "justify-end" : ""}`}><dt className="text-slate-500">Engine offense ({engine.covered}/{engine.offense})</dt><dd className="tabular-nums text-sky-300">{pts(engine.total)}</dd></div>
        </dl>
      </div>)}
      <p aria-hidden="true" className="order-2 text-sm font-semibold text-slate-600">VS</p>
    </div>
    <WinBar overview={overview} />
    <p className="break-words border-t border-slate-800 px-5 py-3 text-xs text-slate-400">{matchup.reason} Scores are a platform snapshot ({matchup.recorded_at ?? "time unknown"}), not a live feed; estimates are full-game pregame points, never remaining points.</p>
    <details className="border-t border-slate-800 px-5 py-2">
      <summary className="min-h-11 cursor-pointer py-3 text-sm text-slate-300">Starter contributions</summary>
      <div className="grid gap-6 pb-4 lg:grid-cols-2">{sides.map(({ key, side }) => <table key={key} className="w-full text-sm">
        <caption className="pb-2 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">{side?.name ?? key}</caption>
        <thead className="text-xs text-slate-500"><tr><th scope="col" className="w-12 py-1 text-left font-normal">Slot</th><th scope="col" className="py-1 text-left font-normal">Player</th><th scope="col" className="py-1 text-right font-normal">Proj</th><th scope="col" className="py-1 text-right font-normal">Engine</th></tr></thead>
        <tbody>{(side?.starters ?? []).map((p, i) => <tr key={i} className="border-t border-slate-800/70">
          <td className="py-2 text-xs text-slate-500">{p.slot}</td>
          <td className="py-2">{p.player_id ? <a href={playerProfileHref(overview.league_id, p.player_id)} className="hover:text-emerald-300 hover:underline">{p.name}</a> : p.name}
            <span className="ml-2 text-[11px] text-slate-500">{evidence(p.source)}{p.locked ? " · locked" : ""}</span></td>
          <td className="py-2 text-right tabular-nums">{pts(p.points)}</td>
          <td className="py-2 text-right tabular-nums text-sky-300">{pts(p.player_id ? players.get(p.player_id)?.engine_week_points : null)}</td>
        </tr>)}</tbody>
      </table>)}</div>
    </details>
    {changes.status === "available" && changes.start.length > 0 && <div className="border-t border-slate-800 p-5" aria-label="Candidate lineup changes">
      <h3 className="text-sm font-semibold">Candidate lineup changes · review only</h3>
      <p className="mt-1 text-xs text-slate-400">{changes.reason}</p>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <div><h4 className="text-xs uppercase tracking-wider text-emerald-300">Start</h4><ul className="mt-2 space-y-1 text-sm">{changes.start.map(p => <li key={p.player_id} className="flex justify-between"><span>{p.name}</span><span className="tabular-nums">{pts(p.points)}</span></li>)}</ul></div>
        <div><h4 className="text-xs uppercase tracking-wider text-slate-400">Bench</h4><ul className="mt-2 space-y-1 text-sm">{changes.bench.map(p => <li key={p.player_id} className="flex justify-between"><span>{p.name}</span><span className="tabular-nums">{pts(p.points)}</span></li>)}</ul></div>
      </div>
    </div>}
  </section>;
}

/** FantasyPros-style win bar from the saved simulation; withheld states say why. */
export function WinBar({ overview }: { overview: Overview }) {
  const o = overview.outcomes;
  if (o.status !== "estimated_research" || o.win_probability == null) return <p className="border-t border-slate-800 px-5 py-3 text-xs text-slate-500">Win probability withheld: {o.reason.replaceAll("_", " ")}{o.blockers.length ? ` (${o.blockers.length} starter${o.blockers.length === 1 ? "" : "s"} blocked, e.g. ${o.blockers[0]})` : ""}.</p>;
  const p = o.win_probability;
  return <div className="border-t border-slate-800 px-5 py-4" aria-label="Win probability research">
    <div className="flex items-center justify-between text-sm font-semibold tabular-nums"><span className="text-emerald-300">{pct(p)}</span><span className="text-[11px] font-medium uppercase tracking-wider text-slate-500">Win probability · simulation research</span><span className="text-slate-300">{pct(1 - p)}</span></div>
    <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-slate-700" role="img" aria-label={`Estimated ${pct(p)} to win`}><div className="bg-emerald-400" style={{ width: `${p * 100}%` }} /></div>
    <p className="mt-2 flex justify-between text-xs text-slate-400 tabular-nums"><span>Range {pts(o.p10)}–{pts(o.p90)}</span>{o.known_final_starters > 0 && <span>{o.known_final_starters} finished starters counted</span>}<span>Range {pts(o.opponent_p10)}–{pts(o.opponent_p90)}</span></p>
    {o.best_changes.length > 0 && o.best_win_probability != null && <p className="mt-2 text-xs text-slate-300">Max-win lineup reaches {pct(o.best_win_probability)}: {o.best_changes.map(c => `start ${c.start_name} over ${c.replaces_name}`).join("; ")}. <a className="text-emerald-300 underline" href={`/workspace?view=fantasy&league=${encodeURIComponent(overview.league_id)}&tool=startsit`}>Start/Sit</a></p>}
  </div>;
}
