import type { Overview } from "@/lib/workspace";
import { availabilityLabel, playerProfileHref, playerResearchHref, pts } from "@/lib/workspace";
import { EngineCells, byPosition, engineFirstWeek } from "./WorkspaceOutlook";
import { Meter } from "./OutcomeCharts";
import type { PlayerDetail } from "@/lib/workspace-api.generated";

function PlayerEvidence({ player, league }: { player: PlayerDetail; league:string }) {
  return <details className="rounded-lg border border-slate-700 p-4">
    <summary className="cursor-pointer text-sm font-medium">{player.name} · {player.position ?? "Unknown position"} · {player.team ?? "Unknown team"}{player.locked ? " · locked" : ""}</summary>
    <dl className="mt-3 space-y-2 text-sm text-slate-300">
      <div><a href={playerResearchHref(league,player.player_id)} className="inline-flex min-h-11 items-center text-emerald-200 underline">Open full player research</a></div>
      <div><dt className="text-slate-400">Pregame estimate</dt><dd>{player.points == null ? "Unknown" : player.points.toFixed(1)} · {player.source.replaceAll("_", " ")}</dd></div>
      <div><dt className="text-slate-400">Projection feed observed</dt><dd>{player.projection_observed_at ?? "Unknown"}</dd></div>
      <div><dt className="text-slate-400">Platform injury designation</dt><dd>{player.injury_status ?? "Not supplied — not confirmation of availability"}</dd></div>
      <div><dt className="text-slate-400">Availability evidence</dt><dd>{availabilityLabel(player.availability_status)}</dd></div>
      <div><dt className="text-slate-400">Game-linked injury evidence</dt><dd>{(player.game_availability_status ?? 'not_collected').replaceAll('_',' ')}{player.game_availability_hold ? ' · Recommendation held' : ''} · Observed {player.game_availability_observed_at ?? 'unknown'}. Event-linked reports are not an official inactive list.</dd></div>
      <div><dt className="text-slate-400">Canonical identity</dt><dd>{player.identity_status.replaceAll("_", " ")}</dd></div>
      <div><dt className="text-slate-400">Scoring history</dt><dd>{player.complete_scored_games ?? "Unknown"} complete scored games · {player.history_status.replaceAll("_", " ")} · Through {player.history_through ?? "unknown"}</dd></div>
      <div><dt className="text-slate-400">Uncertainty history · separate from ROS</dt><dd>{player.distribution ? `${player.distribution.observed_samples} usable observed samples · ${player.distribution.source.replaceAll('_',' ')}` : 'Unknown'}{player.distribution?.assumed_prior ? ' · Assumed positional prior, not measured history' : ''}. Historical variability is not prospective forecast validation.</dd></div>
      {!!player.missing_scoring_keys.length && <div><dt className="text-amber-200">Missing scoring categories</dt><dd>{player.missing_scoring_keys.join(", ")}</dd></div>}
    </dl>
  </details>;
}

export function WorkspaceRoster({ overview, section = 'team' }: { overview: Overview; section?: 'team' | 'waivers' }) {
  const { waivers, roster_players: players } = overview;
  const positions = [...new Set(waivers.moves.map(move => move.add.position ?? 'Unknown position'))].sort();
  const first = engineFirstWeek(overview);
  return <div className="mt-6 space-y-6">
    {section === 'waivers' && <section aria-label="Waiver research">
      <h3 className="text-lg font-semibold">Waiver research</h3>
      <p className="mt-2 text-sm text-slate-300">Alternative add/drop candidates, not a combined transaction plan. Gains compare optimized unstarted slots only; they are not ROS value, guaranteed points, or win probability.</p>
      <p className="mt-2 text-xs text-slate-400">Snapshot status: {waivers.status.replaceAll("_", " ")}. Platform availability, waiver timing, budget, and roster rules must be confirmed before acting.</p>
      {!waivers.moves.length && <p role="status" className="mt-3 rounded-lg border border-slate-700 p-4 text-sm">{waivers.status === "lock_preserving_candidate" ? "No display-eligible positive-gain moves in this checkpoint. This does not mean no useful free agents exist." : "Waiver comparisons are currently unavailable or withheld. Missing evidence is not a zero-value recommendation."}</p>}
      {!!waivers.excluded_moves && <p className="mt-2 text-sm text-amber-200">{waivers.excluded_moves} stored candidate(s) withheld because roster, lock, or comparison evidence is incomplete.</p>}
      {!!waivers.moves.length && <p className="mt-3 text-xs text-slate-400">Grouped by the added player’s position; ordered by estimated unstarted-slot gain within each group. This is not a rest-of-season waiver ranking.</p>}
      <div className="mt-3 space-y-4">{positions.map(position => <details key={position} open className="rounded-xl border border-slate-700 p-4"><summary className="min-h-11 cursor-pointer font-semibold">{position} · {waivers.moves.filter(move=>(move.add.position ?? 'Unknown position')===position).length} alternatives</summary><div className="space-y-3">{waivers.moves.filter(move=>(move.add.position ?? 'Unknown position')===position).sort((a,b)=>b.unstarted_slot_gain-a.unstarted_slot_gain).map((move, i) => <article key={`${move.add.player_id}-${move.drop.player_id}-${i}`} className="rounded-lg border border-slate-700 p-4">
        <h4 className="font-medium">Research {move.add.name} for {move.drop.name}</h4>
        <div className="mt-3 rounded-lg border border-amber-800 bg-amber-950/20 p-3 text-sm text-amber-100">
          <p className="font-semibold">Drop decision unresolved · research only</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">{(move.retention_warnings?.length ? move.retention_warnings : ['Long-term roster cost is not included in the weekly gain. This is not a drop recommendation.']).map(warning => <li key={warning}>{warning}</li>)}</ul>
        </div>
        <p className="my-3 text-sm text-emerald-200">+{move.unstarted_slot_gain.toFixed(1)} estimated points in unstarted slots</p>
        {!!move.equivalent_drops?.length && <details className="mb-3 rounded-lg border border-slate-700 p-3"><summary className="min-h-11 cursor-pointer text-sm">Other drops with the same weekly gain ({move.equivalent_drops.length})</summary><p className="my-2 text-xs text-slate-400">Equal rounded weekly gains do not establish equal long-term value. These are alternative scenarios, not additional transactions.</p><ul className="space-y-2">{move.equivalent_drops.map(player=><li key={player.player_id}><a className="inline-flex min-h-11 items-center text-sm text-emerald-200 underline" href={playerResearchHref(overview.league_id,move.add.player_id,player.player_id)}>Research {move.add.name} for {player.name}</a></li>)}</ul></details>}
        <a href={playerResearchHref(overview.league_id,move.add.player_id,move.drop.player_id)} className="mb-3 inline-flex min-h-11 items-center text-sm text-emerald-200 underline">Compare add/drop evidence</a>
        <div className="grid gap-3 lg:grid-cols-2"><div><p className="mb-2 text-xs font-semibold uppercase text-emerald-300">Potential addition</p><PlayerEvidence player={move.add} league={overview.league_id} /></div><div><p className="mb-2 text-xs font-semibold uppercase text-slate-400">Corresponding drop</p><PlayerEvidence player={move.drop} league={overview.league_id} /></div></div>
      </article>)}</div></details>)}</div>
    </section>}
    {section === 'team' && <section aria-label="Your roster evidence">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <h2 className="text-lg font-semibold">Roster</h2>
        <p className="text-xs text-slate-500">Projection = Sleeper + engine v2 blend · v1 = research, conditional on playing</p>
      </div>
      {!players.length ? <p className="text-sm text-slate-400">No uniquely bound roster is available in this snapshot.</p> : <div className="workspace-scrollbar overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full min-w-[54rem] text-sm">
          <thead className="bg-slate-900/70 text-xs text-slate-400"><tr>
            <th scope="col" className="px-3 py-2 text-left font-medium">Player</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">Projection</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">Sleeper</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">v2</th>
            <th scope="col" className="px-2 py-2 text-right font-medium">v1</th>
            {Array.from({length: 4}, (_, i) => <th key={i} scope="col" className="px-0.5 py-2 text-center font-medium">W{first + 1 + i}</th>)}
            <th scope="col" className="px-3 py-2 text-right font-medium">ROS</th>
            <th scope="col" className="px-2 py-2 text-left font-medium">Upside</th>
            <th scope="col" className="px-2 py-2 text-left font-medium">Bust</th>
          </tr></thead>
          <tbody>{[...players].sort(byPosition).map(player => <tr key={player.player_id} className="border-t border-slate-800/70">
            <th scope="row" className="max-w-[14rem] px-3 py-1.5 text-left font-normal">
              <a href={playerProfileHref(overview.league_id, player.player_id)} className="block truncate font-medium hover:text-emerald-300 hover:underline">{player.name}</a>
              <span className="text-[11px] text-slate-500">{player.position ?? '?'} · {player.team ?? 'FA'}{player.locked ? ' · locked' : ''}{player.injury_status ? <span className="text-amber-300"> · {player.injury_status}</span> : null}{player.reserve_slot ? <span className="ml-1 rounded bg-slate-700 px-1.5 py-0.5 text-[10px] font-semibold text-slate-200">{player.reserve_slot}</span> : null}{player.never_drop ? <span className="ml-1 rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-200">KEEP</span> : null}</span>
            </th>
            <td className="px-2 text-right tabular-nums">{pts(player.points)}</td>
            <td className="px-2 text-right tabular-nums text-slate-400">{pts(player.provider_week_points)}</td>
            <td className="px-2 text-right tabular-nums text-sky-300">{pts(player.engine_v2_week_points)}</td>
            <td className="px-2 text-right tabular-nums text-sky-300">{pts(player.engine_week_points)}</td>
            {player.engine_status.startsWith('research') ? <EngineCells player={player} first={first + 1} count={4} />
              : <td colSpan={4} className="px-2 text-center text-xs text-slate-600">{player.engine_status === 'position_not_modeled' ? 'K/DEF not modeled' : 'No engine research'}</td>}
            <td className="px-3 text-right tabular-nums">{pts(player.engine_ros_points)}</td>
            <td className="px-2"><Meter probability={overview.outcomes?.player_ranges?.[player.player_id]?.boom_probability} tone="up" label="Boom" /></td>
            <td className="px-2"><Meter probability={overview.outcomes?.player_ranges?.[player.player_id]?.bust_probability} tone="down" label="Bust" /></td>
          </tr>)}</tbody>
        </table>
      </div>}
      <p className="mt-2 text-xs text-slate-500">Projection = half Sleeper, half engine v2 where v2 projects the player (Sleeper alone otherwise); v1 is research. Full-game estimates, not remaining points. Locked also covers missing kickoff or game binding. Select a player for availability, identity and history evidence.</p>
    </section>}
  </div>;
}
