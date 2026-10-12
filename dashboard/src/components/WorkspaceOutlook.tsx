import { engineWeeks, playerProfileHref, pts, type Overview, environmentLabel } from "@/lib/workspace";
import type { PlayerDetail } from "@/lib/workspace-api.generated";

export const POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"];
export const byPosition = (a: PlayerDetail, b: PlayerDetail) =>
  (POSITION_ORDER.indexOf(a.position ?? "") + 99) % 99 - (POSITION_ORDER.indexOf(b.position ?? "") + 99) % 99
  || (b.engine_ros_points ?? -1) - (a.engine_ros_points ?? -1) || a.name.localeCompare(b.name);

/** Intensity scales with points; unlined weeks are hatched, not hidden. */
function heat(points: number) {
  const level = Math.min(4, Math.floor(points / 5));
  return ["bg-slate-800 text-slate-300", "bg-sky-950 text-sky-200", "bg-sky-900 text-sky-100", "bg-sky-700 text-white", "bg-sky-500 text-slate-950"][level];
}

export function EngineCells({ player, first, count }: { player: PlayerDetail; first: number; count: number }) {
  return <>{engineWeeks(player, first, count).map((cell, i) => <td key={i} className="px-0.5 py-1.5 text-center">
    {cell ? <span title={`Week ${cell.week} · ${environmentLabel(cell.environment)}`}
      className={`inline-block min-w-10 rounded px-1.5 py-1 text-xs tabular-nums ${heat(cell.points)} ${cell.environment === "market_line" ? "" : "opacity-70 ring-1 ring-inset ring-slate-600"}`}>{cell.points.toFixed(1)}</span>
      : <span className="text-xs text-slate-600" title="No projected game: bye, not modeled, unavailable, or game already started">—</span>}
  </td>)}</>;
}

export function engineFirstWeek(overview: Overview) {
  const weeks = overview.comparison_players.flatMap(p => p.engine_weeks.map(w => w.week));
  return weeks.length ? Math.min(...weeks) : overview.week ?? 1;
}

/** Your roster's engine research for the coming weeks. Offense only; never a decision input. */
export function WorkspaceOutlook({ overview }: { overview: Overview }) {
  const first = engineFirstWeek(overview), count = 5;
  const players = [...overview.roster_players].sort(byPosition);
  const modeled = players.filter(p => p.engine_status === "research" || p.engine_status === "research_partial_scoring");
  return <section className="mt-8" aria-label="Roster outlook">
    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
      <h2 className="text-lg font-semibold">Roster outlook <span className="ml-1 rounded bg-sky-500/15 px-2 py-0.5 align-middle text-[11px] font-medium uppercase tracking-wider text-sky-300">Engine research</span></h2>
      <p className="text-xs text-slate-500">Conditional on playing · outlined cells have no market line yet</p>
    </div>
    {!modeled.length ? <p role="status" className="rounded-xl border border-slate-800 p-4 text-sm text-slate-400">No engine research is attached to this snapshot (stale, not yet generated, or no QB/RB/WR/TE resolved). Missing is not zero.</p> :
    <div className="workspace-scrollbar overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full min-w-[36rem] text-sm">
        <thead className="bg-slate-900/70 text-xs text-slate-400"><tr>
          <th scope="col" className="px-3 py-2 text-left font-medium">Player</th>
          {Array.from({ length: count }, (_, i) => <th key={i} scope="col" className="px-0.5 py-2 text-center font-medium">W{first + i}</th>)}
          <th scope="col" className="px-3 py-2 text-right font-medium">ROS</th>
        </tr></thead>
        <tbody>{players.map(p => <tr key={p.player_id} className="border-t border-slate-800/70">
          <th scope="row" className="max-w-[12rem] px-3 py-1.5 text-left font-normal">
            <a href={playerProfileHref(overview.league_id, p.player_id)} className="block truncate font-medium hover:text-emerald-300 hover:underline">{p.name}</a>
            <span className="text-[11px] text-slate-500">{p.position ?? "?"} · {p.team ?? "FA"}{p.injury_status ? <span className="text-amber-300"> · {p.injury_status}</span> : null}</span>
          </th>
          {p.engine_status.startsWith("research") ? <EngineCells player={p} first={first} count={count} />
            : <td colSpan={count} className="px-2 text-center text-xs text-slate-600">{p.engine_status === "position_not_modeled" ? "K/DEF not modeled" : "No engine research"}</td>}
          <td className="px-3 text-right tabular-nums">{pts(p.engine_ros_points)}<span className="block text-[10px] text-slate-500">{p.engine_ros_games ? `${p.engine_ros_games} g` : ""}</span></td>
        </tr>)}</tbody>
      </table>
    </div>}
  </section>;
}
