import { playerProfileHref, pts, type Overview } from "@/lib/workspace";
import { SosStars } from "./OutcomeCharts";

const TIER: Record<string, [string, string]> = {
  priority: ["Priority", "bg-emerald-400 text-slate-950"], consider: ["Consider", "bg-emerald-400/20 text-emerald-200"],
  stream: ["Stream", "bg-sky-400/20 text-sky-200"], depth: ["Depth", "bg-slate-700 text-slate-300"],
};
const signed = (v: number | null | undefined) => v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}`;
type PlanningFields = {
  horizon_weeks?: number;
  thresholds?: {min_lineup_gain: number; min_stream_gain: number};
  coverage_blockers?: {week: number | null; missing_player_ids: string[];
    missing_players?: {name: string; position?: string | null}[]}[];
};
type RowPlanningFields = {
  weekly?: {week: number; gain: number; add_status?: string}[];
  alternative_drops?: {drop_id: string; name?: string; lineup_gain: number; weekly?: {week: number; gain: number}[]}[];
  needed_by_week?: number | null;
  target_game_kickoff?: string | null;
};

/** Waiver guidance: marginal starting-lineup points over a selected horizon. */
export function WorkspaceEngineWaivers({ overview }: { overview: Overview }) {
  const view = overview.engine_waivers as Overview["engine_waivers"] & PlanningFields;
  const weeks = view.horizon_weeks ?? 2;
  const priority = view.waiver_type === "rolling" && view.waiver_position != null && view.teams
    ? `Rolling waivers · your priority ${view.waiver_position} of ${view.teams}` : view.waiver_type === "unknown" ? "Waiver order not supplied by this platform" : `Waiver type: ${view.waiver_type.replaceAll("_", " ")}`;
  return <section className="mt-6" aria-label="Waiver guidance">
    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
      <h2 className="text-lg font-semibold">Waiver guidance <span className="ml-1 rounded bg-sky-500/15 px-2 py-0.5 align-middle text-[11px] font-medium uppercase tracking-wider text-sky-300">Engine research</span></h2>
      <p className="text-xs text-slate-400">{priority}{view.waiver_clear_days != null ? ` · dropped players clear in ${view.waiver_clear_days} days` : ""}</p>
    </div>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <nav aria-label="Waiver planning horizon" className="inline-flex gap-1 rounded-lg bg-slate-900 p-1">
        {[2, 3, 4].map(horizon => <a key={horizon} aria-current={weeks === horizon ? "page" : undefined}
          href={`/workspace?view=fantasy&league=${encodeURIComponent(overview.league_id)}&tool=waivers&horizon=${horizon}`}
          className={`rounded-md px-3 py-2 text-xs ${weeks === horizon ? "bg-emerald-400 text-slate-950" : "text-slate-400 hover:text-white"}`}>
          {horizon} weeks</a>)}
      </nav>
      {view.thresholds && <p className="text-xs text-slate-500">Minimum improvement: {pts(view.thresholds.min_lineup_gain)} lineup pts · {pts(view.thresholds.min_stream_gain)} weekly streaming pts</p>}
    </div>
    {!!view.coverage_blockers?.length && <div className="mb-3 rounded-lg border border-amber-400/15 p-3 text-xs text-amber-300" role="status">
      <p>Offensive comparisons are waiting on complete projection coverage. Available streaming suggestions appear below.</p>
      <ul className="mt-2 space-y-1">{view.coverage_blockers.map((b, i) => {
        const grouped = new Map<string, string[]>();
        for (const p of b.missing_players ?? []) grouped.set(p.position ?? "Unknown position", [...(grouped.get(p.position ?? "Unknown position") ?? []), p.name]);
        const names = [...grouped].map(([position, names]) => `${position}: ${names.join(", ")}`).join(" · ");
        return <li key={i}>{b.week == null ? "Roster" : `Week ${b.week}`}: {names || `${b.missing_player_ids.length} missing player forecasts`}</li>;
      })}</ul>
    </div>}
    {!view.rows.length ? <p role="status" className="rounded-xl border border-slate-800 p-4 text-sm text-slate-400">No waiver guidance for this snapshot ({view.status.replaceAll("_", " ")}). Missing is not a zero-value result.</p> :
    <ol className="space-y-2">{view.rows.map((value, i) => {
      const row = value as typeof value & RowPlanningFields;
      const [label, tone] = TIER[row.tier];
      return <li key={`${row.add.player_id}:${i}`} className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider ${tone}`}>{label}</span>
          <a href={playerProfileHref(overview.league_id, row.add.player_id)} className="font-semibold hover:text-emerald-300 hover:underline">Add {row.add.name}</a>
          <span className="text-xs text-slate-500">{row.add.position} · {row.add.team ?? "FA"}</span>
          <span className="text-slate-600">→</span>
          {row.compare ? <a href={playerProfileHref(overview.league_id, row.compare.player_id)} className="text-sm text-slate-300 hover:underline">drop {row.compare.name}</a> : null}
          <dl className="ml-auto flex gap-4 text-right text-xs">
            {row.ros_gain != null && <div><dt className="text-slate-500">{weeks}-week lineup gain</dt><dd className="text-base font-semibold tabular-nums text-emerald-300">{signed(row.ros_gain)}</dd></div>}
            <div><dt className="text-slate-500">{row.week != null ? `Week ${row.week}` : "This week"}</dt><dd className="text-base font-semibold tabular-nums">{signed(row.week_gain)}</dd></div>
          </dl>
        </div>
        {row.add.position !== "K" && row.add.position !== "DEF" && <p className="mt-2 flex flex-wrap gap-3"><SosStars stars={row.add.sos_ros_stars} label="Schedule ROS" /><SosStars stars={row.add.sos_next4_stars} label="Next 4" /></p>}
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-slate-400">{row.reasons.map(r => <li key={r}>{r}</li>)}</ul>
        {!!row.weekly?.length && <p className="mt-3 flex flex-wrap gap-2 text-xs" aria-label="Weekly lineup impact">{row.weekly.map(w =>
          <span key={w.week} className="rounded bg-slate-800 px-2 py-1 text-slate-300">W{w.week} <span className={w.gain > 0 ? "text-emerald-300" : w.gain < 0 ? "text-amber-300" : "text-slate-400"}>{signed(w.gain)}</span>{w.add_status === "verified_bye" ? " · bye" : w.add_status === "confirmed_unavailable" ? " · unavailable" : ""}</span>)}</p>}
        {row.needed_by_week != null && <p className="mt-2 text-xs text-slate-400">Useful by Week {row.needed_by_week}{row.target_game_kickoff ? ` · kickoff ${new Date(row.target_game_kickoff).toLocaleString("en-US", {timeZone: "America/Chicago", month: "short", day: "numeric", hour: "numeric", minute: "2-digit"})} CT` : ""}. Check your platform’s claim deadline.</p>}
        {!!row.alternative_drops?.length && <details className="mt-3 text-xs text-slate-400">
          <summary className="cursor-pointer hover:text-slate-200">Compare other drops</summary>
          <ul className="mt-2 space-y-1">{row.alternative_drops.map(drop => <li key={drop.drop_id} className="flex justify-between gap-3">
            <a href={playerProfileHref(overview.league_id, drop.drop_id)} className="hover:text-emerald-300 hover:underline">{drop.name ?? drop.drop_id}</a>
            <span>{signed(drop.lineup_gain)} lineup pts</span>
          </li>)}</ul>
        </details>}
      </li>;
    })}</ol>}
    {!!view.protected?.length && <p className="mt-3 text-xs text-slate-400">Never suggested as drops: {view.protected.map(p => `${p.name}${p.reserve_slot ? ` (${p.reserve_slot})` : ""}`).join(", ")}. Players in IR or taxi slots stay on your roster.</p>}
    {!!view.trending.length && <div className="mt-4 rounded-xl border border-slate-800 p-4">
      <h3 className="text-sm font-semibold">Trending adds on Sleeper <span className="font-normal text-slate-500">· last 24 h · unrostered here</span></h3>
      <ul className="mt-2 flex flex-wrap gap-2">{view.trending.map(t => <li key={t.player.player_id}>
        <a href={playerProfileHref(overview.league_id, t.player.player_id)} className="inline-flex min-h-9 items-center gap-2 rounded-full border border-slate-700 px-3 text-xs hover:border-emerald-500">
          {t.player.name} <span className="text-slate-500">{t.player.position}</span><span className="tabular-nums text-emerald-300">+{t.adds.toLocaleString()}</span></a></li>)}</ul>
      <p className="mt-2 text-[11px] text-slate-500">Crowd signal from Sleeper, shown for context; it does not change the guidance above.</p>
    </div>}
    <details className="mt-3 text-xs text-slate-500"><summary className="cursor-pointer">How waiver planning works</summary><p className="mt-2">{view.tier_rule} Each row compares your best offensive lineup over the selected {weeks} weeks with and without the swap. Verified byes and confirmed absences count as zero; missing projections withhold the comparison. Forecasts are conditional on playing. Candidates are the top engine-projected unrostered players in this snapshot.</p></details>
  </section>;
}
