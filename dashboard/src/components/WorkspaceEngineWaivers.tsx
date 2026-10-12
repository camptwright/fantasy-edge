import { playerProfileHref, pts, type Overview } from "@/lib/workspace";

const TIER: Record<string, [string, string]> = {
  priority: ["Priority", "bg-emerald-400 text-slate-950"], consider: ["Consider", "bg-emerald-400/20 text-emerald-200"],
  stream: ["Stream", "bg-sky-400/20 text-sky-200"], depth: ["Depth", "bg-slate-700 text-slate-300"],
};
const signed = (v: number | null | undefined) => v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}`;

/** Waiver guidance: marginal starting-lineup points over the remaining weeks. Research only. */
export function WorkspaceEngineWaivers({ overview }: { overview: Overview }) {
  const view = overview.engine_waivers;
  const priority = view.waiver_type === "rolling" && view.waiver_position != null && view.teams
    ? `Rolling waivers · your priority ${view.waiver_position} of ${view.teams}` : view.waiver_type === "unknown" ? "Waiver order not supplied by this platform" : `Waiver type: ${view.waiver_type.replaceAll("_", " ")}`;
  return <section className="mt-6" aria-label="Waiver guidance">
    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
      <h2 className="text-lg font-semibold">Waiver guidance <span className="ml-1 rounded bg-sky-500/15 px-2 py-0.5 align-middle text-[11px] font-medium uppercase tracking-wider text-sky-300">Engine research</span></h2>
      <p className="text-xs text-slate-400">{priority}{view.waiver_clear_days != null ? ` · dropped players clear in ${view.waiver_clear_days} days` : ""}</p>
    </div>
    {view.status !== "research" || !view.rows.length ? <p role="status" className="rounded-xl border border-slate-800 p-4 text-sm text-slate-400">No waiver guidance for this snapshot ({view.status.replaceAll("_", " ")}). Missing is not a zero-value result.</p> :
    <ol className="space-y-2">{view.rows.map((row, i) => {
      const [label, tone] = TIER[row.tier];
      return <li key={`${row.add.player_id}:${i}`} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider ${tone}`}>{label}</span>
          <a href={playerProfileHref(overview.league_id, row.add.player_id)} className="font-semibold hover:text-emerald-300 hover:underline">Add {row.add.name}</a>
          <span className="text-xs text-slate-500">{row.add.position} · {row.add.team ?? "FA"}</span>
          <span className="text-slate-600">→</span>
          {row.compare ? <a href={playerProfileHref(overview.league_id, row.compare.player_id)} className="text-sm text-slate-300 hover:underline">drop {row.compare.name}</a> : null}
          <dl className="ml-auto flex gap-4 text-right text-xs">
            {row.ros_gain != null && <div><dt className="text-slate-500">Lineup pts ROS</dt><dd className="text-base font-semibold tabular-nums text-emerald-300">{signed(row.ros_gain)}</dd></div>}
            <div><dt className="text-slate-500">{row.week != null ? `Week ${row.week}` : "This week"}</dt><dd className="text-base font-semibold tabular-nums">{signed(row.week_gain)}</dd></div>
            {row.add.engine_ros_points != null && <div><dt className="text-slate-500">Add ROS</dt><dd className="text-base tabular-nums text-slate-300">{pts(row.add.engine_ros_points)}</dd></div>}
          </dl>
        </div>
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-slate-400">{row.reasons.map(r => <li key={r}>{r}</li>)}</ul>
      </li>;
    })}</ol>}
    <p className="mt-2 text-xs text-slate-500">{view.tier_rule} Each row re-solves your best offensive lineup every remaining week with and without the swap, so bench depth and byes count; conditional on playing. Candidates are the top engine-projected unrostered players in this snapshot. Confirm availability and claim timing on your platform.</p>
  </section>;
}
