import { availabilityLabel, environmentLabel, fantasyToolHref, pct, playerResearchHref, pts, type Overview } from "@/lib/workspace";
import { DistributionCurve, Meter } from "./OutcomeCharts";
import { BOOM_BUST } from "./WorkspaceStartSit";

function heatClass(points: number) {
  return points >= 20 ? "bg-emerald-500/30 text-emerald-100" : points >= 12 ? "bg-emerald-500/15 text-emerald-200"
    : points >= 6 ? "bg-slate-800 text-slate-200" : "bg-rose-500/15 text-rose-200";
}

const OWNERSHIP: Record<string, string> = { your_roster: "Your roster", other_roster: "Rostered", unrostered_snapshot: "Unrostered in snapshot", unknown: "Ownership unknown" };

function Stat({ label, value, sub, tone = "" }: { label: string; value: string; sub?: string; tone?: string }) {
  return <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
    <dt className="text-xs text-slate-400">{label}</dt>
    <dd className={`mt-1 text-2xl font-semibold tabular-nums ${tone}`}>{value}</dd>
    {sub && <dd className="mt-1 text-[11px] text-slate-500">{sub}</dd>}
  </div>;
}

/** Dedicated player screen from the saved checkpoint; no extra requests. */
export function WorkspacePlayerProfile({ overview, playerId }: { overview: Overview; playerId?: string }) {
  const player = overview.comparison_players.find(p => p.player_id === playerId)
    ?? overview.roster_players.find(p => p.player_id === playerId);
  if (!player) return <section role="status" className="rounded-xl border border-amber-800 p-5">
    <h2 className="font-semibold">Player not in this snapshot</h2>
    <p className="mt-2 text-sm text-slate-300">The linked player is missing from this league’s current checkpoint. No substitute was selected.</p>
    <a href={fantasyToolHref("players", overview.league_id)} className="mt-3 inline-flex min-h-11 items-center text-sm text-emerald-200 underline">Search players</a>
  </section>;
  const max = Math.max(10, ...player.engine_weeks.map(w => w.points));
  const research = player.engine_status.startsWith("research");
  return <article aria-labelledby="player-name">
    <header className="flex flex-wrap items-center gap-4 rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-900 to-slate-950 p-5">
      <span aria-hidden="true" className="grid h-14 w-14 place-items-center rounded-full bg-slate-800 text-lg font-bold text-slate-300">{player.position ?? "?"}</span>
      <div className="min-w-0 flex-1">
        <h2 id="player-name" className="text-2xl font-semibold tracking-tight">{player.name}</h2>
        <p className="mt-1 flex flex-wrap gap-2 text-xs">
          <span className="rounded-full bg-slate-800 px-2.5 py-1 text-slate-300">{player.team ?? "Team unknown"}</span>
          <span className="rounded-full bg-slate-800 px-2.5 py-1 text-slate-300">{OWNERSHIP[player.ownership] ?? player.ownership}{player.roster_names.length ? ` · ${player.roster_names.join(", ")}` : ""}</span>
          {player.injury_status && <span className="rounded-full bg-amber-400/15 px-2.5 py-1 text-amber-200">{player.injury_status}</span>}
          {player.locked && <span className="rounded-full bg-slate-800 px-2.5 py-1 text-slate-400">Locked / game binding unknown</span>}
        </p>
      </div>
      <a href={playerResearchHref(overview.league_id, player.player_id)} className="inline-flex min-h-11 items-center rounded-lg border border-slate-700 px-4 text-sm hover:border-emerald-500">Compare</a>
    </header>
    <dl className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3">
      <Stat label={`Week ${overview.week ?? "?"} provider`} value={pts(player.points)} sub={player.source.replaceAll("_", " ")} />
      <Stat label="ESPN this week" value={pts(player.espn_week_points)} sub={player.espn_week_points == null ? "Not captured for this week" : "Your league's scoring"} />
      <Stat label="Consensus" value={pts(player.consensus_week_points)} sub={player.consensus_week_points == null ? "Needs two sources" : `Mean of ${player.consensus_sources} sources · research`} tone="text-emerald-300" />
      <Stat label="Engine this week" value={pts(player.engine_week_points)} sub="Research · if playing" tone="text-sky-300" />
      <Stat label="Engine rest of season" value={pts(player.engine_ros_points)} sub={research ? `${player.engine_ros_games} games · ${player.engine_ros_lined_games} with market lines` : player.engine_status.replaceAll("_", " ")} tone="text-sky-300" />
      <Stat label="History-based ROS" value={pts(player.ros_points)} sub={player.ros_status.replaceAll("_", " ")} />
    </dl>
    {(() => {
      const range = overview.outcomes.player_ranges[player.player_id];
      const [boom, bust] = BOOM_BUST[player.position ?? ""] ?? [20, 6];
      return range?.density.length ? <section className="mt-6 rounded-xl border border-slate-800 p-5" aria-label="This week's range">
        <h3 className="font-semibold">Week {overview.week ?? "?"} range <span className="ml-1 text-xs font-normal text-slate-500">simulation research · {range.basis.replaceAll("_", " ")}</span></h3>
        <div className="mt-3 grid gap-4 md:grid-cols-[1fr_14rem]">
          <DistributionCurve ranges={[{ label: player.name, range }]} colors={["#34d399"]} boom={boom} bust={bust} />
          <dl className="grid grid-cols-2 content-start gap-3 text-sm">
            <div><dt className="text-xs text-slate-500">10th pct</dt><dd className="tabular-nums">{pts(range.p10)}</dd></div>
            <div><dt className="text-xs text-slate-500">90th pct</dt><dd className="tabular-nums">{pts(range.p90)}</dd></div>
            <div><dt className="text-xs text-slate-500">Boom ≥{boom}</dt><dd className="flex items-center gap-2 tabular-nums">{pct(range.boom_probability)} <Meter probability={range.boom_probability} tone="up" label="Boom" /></dd></div>
            <div><dt className="text-xs text-slate-500">Bust ≤{bust}</dt><dd className="flex items-center gap-2 tabular-nums">{pct(range.bust_probability)} <Meter probability={range.bust_probability} tone="down" label="Bust" /></dd></div>
          </dl>
        </div>
      </section> : null;
    })()}
    <section className="mt-6 overflow-hidden rounded-xl border border-slate-800" aria-label="Game log and projections">
      <h3 className="p-5 pb-3 font-semibold">Game log <span className="ml-1 text-xs font-normal text-slate-500">league-scored results, then engine projections</span></h3>
      {!player.game_log.length && !player.engine_weeks.length ? <p className="px-5 pb-5 text-sm text-slate-400">No league-scored history or engine weeks for this player.</p> :
      <table className="w-full text-sm">
        <thead className="bg-slate-900/70 text-xs text-slate-400"><tr><th scope="col" className="px-5 py-2 text-left font-medium">Week</th><th scope="col" className="px-5 py-2 text-right font-medium">Points</th><th scope="col" className="px-5 py-2 text-left font-medium">Basis</th></tr></thead>
        <tbody>
          {player.game_log.map(g => <tr key={`a${g.week}`} className="border-t border-slate-800/70"><td className="px-5 py-1.5 tabular-nums">{g.week}</td>
            <td className="px-5 py-1.5 text-right"><span className={`inline-block min-w-12 rounded px-2 py-0.5 text-center tabular-nums ${heatClass(g.points)}`}>{g.points.toFixed(1)}</span></td><td className="px-5 py-1.5 text-xs text-slate-500">Actual · league scoring</td></tr>)}
          {player.engine_weeks.length > 0 && <tr><td colSpan={3} className="border-t border-dashed border-sky-700/60 px-5 py-1 text-xs font-medium text-sky-300">Projected</td></tr>}
          {player.engine_weeks.map(w => <tr key={`p${w.week}`} className="border-t border-slate-800/70"><td className="px-5 py-1.5 tabular-nums">{w.week}</td>
            <td className="px-5 py-1.5 text-right"><span className="inline-block min-w-12 rounded border border-sky-600/60 px-2 py-0.5 text-center tabular-nums text-sky-200">{w.points.toFixed(1)}</span></td><td className="px-5 py-1.5 text-xs text-slate-500">Engine research · {environmentLabel(w.environment)}</td></tr>)}
        </tbody>
      </table>}
    </section>
    <section className="mt-6 rounded-xl border border-slate-800 p-5" aria-label="Weekly engine research">
      <h3 className="font-semibold">Weekly outlook <span className="ml-1 text-xs font-normal text-slate-500">engine research · outlined bars have no market line yet</span></h3>
      {!player.engine_weeks.length ? <p className="mt-3 text-sm text-slate-400">{player.engine_status === "position_not_modeled" ? "Kickers and team defenses are not modeled by the engine." : "No engine weeks for this player (unresolved identity, unavailable, off the depth chart, or research is stale). Missing is not zero."}</p> :
      <ol className="mt-4 flex h-40 items-end gap-2">{player.engine_weeks.map(w => <li key={w.week} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
        <span className="text-xs tabular-nums text-slate-300">{w.points.toFixed(1)}</span>
        <span aria-hidden="true" className={`w-full max-w-12 rounded-t ${w.environment === "market_line" ? "bg-sky-500" : "bg-sky-500/40 ring-1 ring-inset ring-sky-400/60"}`} style={{ height: `${Math.max(4, (w.points / max) * 100)}%` }} />
        <span className="text-[11px] text-slate-500">W{w.week}</span>
      </li>)}</ol>}
    </section>
    <section className="mt-6 rounded-xl border border-slate-800 p-5" aria-label="Evidence">
      <h3 className="font-semibold">Evidence</h3>
      <dl className="mt-3 grid gap-x-6 gap-y-3 text-sm md:grid-cols-2">
        {([
          ["Platform injury designation", player.injury_status ?? "Not supplied — not confirmation of availability"],
          ["Availability evidence", availabilityLabel(player.availability_status)],
          ["Game-linked injury evidence", `${(player.game_availability_status ?? "not_collected").replaceAll("_", " ")}${player.game_availability_hold ? " · recommendation held" : ""} · observed ${player.game_availability_observed_at ?? "unknown"}`],
          ["Projection feed observed", player.projection_observed_at ?? "Unknown"],
          ["Canonical identity", player.identity_status.replaceAll("_", " ")],
          ["Scoring history", `${player.complete_scored_games ?? "Unknown"} complete scored games · ${player.history_status.replaceAll("_", " ")} · through ${player.history_through ?? "unknown"}`],
          ["Uncertainty history", `${player.distribution.observed_samples} usable samples · ${player.distribution.source.replaceAll("_", " ")}${player.distribution.assumed_prior ? " · assumed positional prior" : ""}`],
          ["Engine research generated", player.engine_generated_at ?? "Unknown"],
          ...(player.missing_scoring_keys.length ? [["Missing scoring categories", player.missing_scoring_keys.join(", ")]] : []),
          ...(player.specialist_ros_research ? [["Specialist research (not promoted)", `${pts(player.specialist_ros_research.points)} per game · ${player.specialist_ros_research.games} games`]] : []),
        ] as [string, string][]).map(([label, value]) => <div key={label}><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-0.5 break-words text-slate-200">{value}</dd></div>)}
      </dl>
    </section>
  </article>;
}
