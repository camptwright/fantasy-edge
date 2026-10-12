import type { Overview } from "@/lib/workspace";

const points = (value: number | null) => value == null ? "Unknown" : value.toFixed(1);
const evidence = (source: string) => source === "estimated" ? "Provider estimate"
  : source === "estimated_history" ? "Recent history · conditional on playing" : "Unpriced / unknown";

/** Server-rendered checkpoint presentation, with no extra API requests. */
export function WorkspaceMatchup({ overview }: { overview: Overview }) {
  const { matchup, lineup_changes: changes } = overview;
  return <div className="mt-6 space-y-5">
    <section aria-label="Matchup snapshot">
      <h3 className="text-lg font-semibold">Your matchup at a glance</h3>
      <p className="mt-2 text-sm text-slate-300">{matchup.reason}</p>
      <p className="mt-2 text-xs text-slate-400">Recorded scores are a platform snapshot, not a live feed. Score observation: {matchup.recorded_at ?? "unknown"}. Estimates are full-game pregame points, never remaining points.</p>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {(["mine", "opponent"] as const).map(key => {
          const side = matchup[key];
          return <section key={key} className="min-w-0 rounded-lg border border-slate-700 p-4">
            <h4 className="font-semibold">{side?.name ?? (key === "mine" ? "Your roster unavailable" : "Opponent unavailable")}</h4>
            {!side ? <p className="mt-2 text-sm text-slate-400">No bound roster in this snapshot. This does not establish a bye.</p> : <>
              <dl className="my-4 grid grid-cols-2 gap-3">
                <div><dt className="text-xs text-slate-400">Recorded score</dt><dd className="text-2xl tabular-nums">{points(side.recorded_points)}</dd></div>
                <div><dt className="text-xs text-slate-400">Pregame estimate</dt><dd className="text-2xl tabular-nums">{points(side.pregame_points)}</dd></div>
              </dl>
              <p className="text-xs text-slate-400">{side.starters.filter(p => p.points != null).length}/{side.starters.length} current slots priced. Locked includes unknown kickoff or game binding.</p>
              <details className="mt-3">
                <summary className="min-h-11 cursor-pointer text-sm text-emerald-200">Current starter contributions</summary>
                <ul className="divide-y divide-slate-800">{side.starters.map((player, i) => <li key={i} className="py-3 text-sm">
                  <div className="flex justify-between gap-3"><span>{player.slot} · {player.name}{player.locked ? " · locked" : ""}</span><span className="tabular-nums">{points(player.points)}</span></div>
                  <p className="mt-1 text-xs text-slate-400">{evidence(player.source)}</p>
                </li>)}</ul>
              </details>
            </>}
          </section>;
        })}
      </div>
    </section>
    <section className="rounded-lg border border-slate-700 p-4" aria-label="Candidate lineup changes">
      <h3 className="font-semibold">Candidate changes · review only</h3>
      <p className="mt-2 text-sm text-slate-300">{changes.reason}</p>
      {changes.status === "available" && changes.start.length > 0 && <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <div><h4 className="text-sm text-emerald-200">Move into starting lineup</h4><ul className="mt-2 space-y-2 text-sm">{changes.start.map(p => <li key={p.player_id}>{p.name} · {points(p.points)} estimated points</li>)}</ul></div>
        <div><h4 className="text-sm text-slate-300">Move to bench</h4><ul className="mt-2 space-y-2 text-sm">{changes.bench.map(p => <li key={p.player_id}>{p.name} · {points(p.points)} estimated points</li>)}</ul></div>
      </div>}
      <p className="mt-3 text-xs text-slate-400">No calibrated win probability or lineup transaction. Confirm player availability and kickoff on your fantasy platform.</p>
    </section>
  </div>;
}
