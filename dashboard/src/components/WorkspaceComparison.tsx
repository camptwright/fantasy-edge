"use client";
import { useEffect, useRef, useState } from "react";
import type { PlayerDetail } from "@/lib/workspace-api.generated";
import { availabilityLabel, comparisonMatches, researchSelection } from "@/lib/workspace";

const number = (n: number | null) => n == null ? "Unknown / withheld" : n.toFixed(1);

export function WorkspaceComparison({ players, initialPlayer, initialCompare, lineup }: { players: PlayerDetail[]; initialPlayer?:string; initialCompare?:string; lineup?:{available:boolean; current:string[]; candidate:string[]; reason:string} }) {
  const initial=researchSelection(players,initialPlayer,initialCompare);
  const [left, setLeft] = useState(initial.left);
  const [right, setRight] = useState(initial.right);
  const [search, setSearch] = useState("");
  const [ownership, setOwnership] = useState("all");
  const [page, setPage] = useState(0);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (left) detailHeading.current?.focus(); }, [left, right]);
  const sorted = [...players].sort((a, b) => a.name.localeCompare(b.name));
  const filtered = sorted.filter(p => comparisonMatches(p, search, ownership));
  const selected = [players.find(p => p.player_id === left), players.find(p => p.player_id === right)];
  const visible = filtered.slice(page * 20, (page + 1) * 20);
  const rows: [string, (p: PlayerDetail) => string][] = [
    ["Ownership in snapshot", p => `${p.ownership.replaceAll("_", " ")}${p.roster_names.length ? ` · ${p.roster_names.join(", ")}` : ""}`],
    ["Position / team", p => `${p.position ?? "Unknown"} / ${p.team ?? "Unknown"}`],
    ["Canonical identity", p => p.identity_status.replaceAll('_', ' ')],
    ["Canonical team binding", p => p.position === 'DEF' || p.position === 'DST' ? p.canonical_team_id ?? 'Unresolved team — not an individual player' : 'Individual player identity applies'],
    ["Weekly pregame estimate", p => number(p.points)],
    ["Weekly source", p => p.source.replaceAll("_", " ")],
    ["Projection observed", p => p.projection_observed_at ?? 'Unknown'],
    ["Lineup lock", p => p.locked ? "Locked or game binding unknown" : "Unlocked in snapshot"],
    ["Your saved lineup context", p => !lineup?.available ? 'Assignment evidence withheld / unavailable' : p.ownership !== 'your_roster' ? 'Outside your corroborated roster — no start/sit assignment inferred' : `${lineup.current.includes(p.player_id) ? 'Current starter' : 'Not a current starter'} · ${lineup.candidate.includes(p.player_id) ? 'Included in stored candidate' : 'Not in stored candidate'}`],
    ["Full ROS candidate points", p => number(p.ros_points)],
    ["Specialist full-score research per game", p => p.specialist_ros_research ? `${number(p.specialist_ros_research.points)} · ${p.specialist_ros_research.games} observed games · not promoted` : 'Not available'],
    ["Specialist conditional ROS research", p => p.specialist_ros_research ? `${number(p.specialist_ros_research.conditional_ros_points)} · ${p.specialist_ros_research.horizon_status.replaceAll('_',' ')}` : 'Not available'],
    ["Specialist research limitations", p => p.specialist_ros_research?.scope ?? 'No specialist research estimate'],
    ["Known-schedule modeled subtotal (may omit scoring categories)", p => number(p.known_schedule_subtotal)],
    ["Schedule evidence", p => p.ros_status.replaceAll("_", " ")],
    ["Known remaining games / unknown kickoffs", p => `${p.known_remaining_games ?? "Unknown"} / ${p.unknown_kickoffs ?? "Unknown"}`],
    ["Through week", p => String(p.through_week ?? "Unknown")],
    ["History evidence", p => `${p.history_status.replaceAll("_", " ")} · ${p.complete_scored_games ?? "Unknown"} complete scored games`],
    ["History through", p => p.history_through ?? 'Unknown'],
    ["Uncertainty history (separate from ROS)", p => p.distribution ? `${p.distribution.source.replaceAll('_',' ')} · ${p.distribution.observed_samples} usable observed samples · ${p.distribution.status.replaceAll('_',' ')}` : 'Unknown'],
    ["Scoring reconciliation checks / mismatches", p => `${p.distribution?.reconciliation_samples ?? 'Unknown'} / ${p.distribution?.reconciliation_mismatches ?? 'Unknown'}`],
    ["Uncertainty evidence limits", p => p.distribution?.assumed_prior ? 'Assumed positional prior — not measured player history or calibrated probability' : 'Historical scoring variability only; not full ROS or prospective validation'],
    ["Missing scoring categories", p => p.missing_scoring_keys.join(", ") || "None reported — see history status"],
    ["Injury designation", p => p.injury_status ?? "Not supplied — availability unconfirmed"],
    ["Availability evidence", p => availabilityLabel(p.availability_status)],
    ["Game-linked injury evidence", p => `${(p.game_availability_status ?? 'not_collected').replaceAll('_',' ')}${p.game_availability_hold ? ' · Recommendation held' : ''}`],
    ["Game evidence observed", p => p.game_availability_observed_at ?? 'Unknown — not game clearance'],
  ];
  return <section aria-label="Player comparison" className="rounded-lg border border-slate-700 p-4">
    <h3 className="text-lg font-semibold">Player research</h3>
    {initial.unavailable && <p role="status" className="my-3 text-sm text-amber-200">A linked player is missing from this league’s current checkpoint, or the comparison repeats the same player. Choose from the current catalog; no substitute was selected.</p>}
    <p className="my-3 text-sm text-slate-400">Search the saved checkpoint catalog, not the entire NFL. Missing search results do not establish availability. Unrostered means unrostered in this snapshot, not immediately claimable.</p>
    <p className="my-3 text-sm text-slate-300">Same league and snapshot. ROS is a conditional, constant-role research estimate, not trade value or a validated forecast. Partial subtotals are not comparable full-season totals. No injury-recovery, dynasty, or keeper adjustments.</p>
    <div className="mb-4 grid gap-3 sm:grid-cols-2">
      <label className="text-sm">Search players<input value={search} onChange={e => {setSearch(e.target.value);setPage(0);}} placeholder="Name, position, or team" className="mt-2 block min-h-11 w-full rounded border border-slate-600 bg-slate-950 p-2" /></label>
      <label className="text-sm">Ownership filter<select value={ownership} onChange={e => {setOwnership(e.target.value);setPage(0);}} className="mt-2 block min-h-11 w-full rounded border border-slate-600 bg-slate-950 p-2">{["all", "your_roster", "other_roster", "unrostered_snapshot", "unknown"].map(value => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select></label>
    </div>
    <p role="status" className="mb-3 text-sm text-slate-400">{filtered.length} matches in {players.length} checkpoint players. Selected players remain available when filters change.</p>
    <p className="mb-3 text-xs text-slate-400">View one player first, then choose a different player to compare. Selections stay when you search; navigation or a new snapshot clears them.</p>
    {selected[0] && <section aria-label="Selected player evidence" className="mb-5 rounded-lg border border-emerald-900 bg-slate-950 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><h4 ref={detailHeading} tabIndex={-1} className="text-lg font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300">{selected[0].name}{selected[1] ? ` vs ${selected[1].name}` : ''}</h4><button onClick={()=>{setLeft('');setRight('');}} className="min-h-11 rounded border border-slate-600 px-3 text-sm">Clear players</button></div>
      <p className="mt-2 text-sm text-slate-400">Saved evidence only. Weekly estimates are full-game pregame points, not remaining points or a start/sit verdict.</p>
      {lineup && <p className="mt-2 text-sm text-slate-400">Lineup context: {lineup.reason} Slot eligibility and interactions must be reviewed in the full lineup; point differences alone are not swap advice.</p>}
      {selected[1] ? <><button onClick={()=>setRight('')} className="mt-3 min-h-11 rounded border border-slate-600 px-3 text-sm">Remove comparison</button><div className="mt-4 overflow-x-auto"><table className="w-full text-left text-sm"><caption className="pb-3 text-left text-slate-400">Evidence comparison — no winner or trade recommendation inferred</caption><thead><tr><th scope="col" className="p-2">Measure</th>{selected.map(p => <th scope="col" key={p!.player_id} className="p-2">{p!.name}</th>)}</tr></thead><tbody>{rows.map(([label, value]) => <tr key={label} className="border-t border-slate-700"><th scope="row" className="p-2 font-normal text-slate-400">{label}</th>{selected.map(p => <td key={p!.player_id} className="p-2">{value(p!)}</td>)}</tr>)}</tbody></table></div></> : <dl className="mt-4 grid gap-4 sm:grid-cols-2">{rows.map(([label,value])=><div key={label}><dt className="text-xs text-slate-400">{label}</dt><dd className="mt-1 break-words text-sm">{value(selected[0]!)}</dd></div>)}</dl>}
    </section>}
    <ul aria-label="Player search results" className="divide-y divide-slate-800 rounded-lg border border-slate-700">{visible.map(p => <li key={p.player_id} className="flex flex-wrap items-center justify-between gap-3 p-3">
      <div className="min-w-0"><p className="font-medium">{p.name}</p><p className="text-xs text-slate-400">{p.position ?? '?'} · {p.team ?? 'Unknown team'} · {p.ownership.replaceAll('_',' ')}</p><p className="mt-1 text-xs text-slate-300">Pregame: {number(p.points)}{p.locked ? ' · Locked / game binding unknown' : ''}{p.injury_status ? ` · ${p.injury_status}` : ''}</p></div>
      <div className="flex gap-2"><button aria-label={`View ${p.name}`} aria-pressed={left === p.player_id} onClick={()=>{setLeft(p.player_id);if(right === p.player_id)setRight('');}} className="min-h-11 rounded border border-emerald-700 px-3 text-sm text-emerald-200">{left === p.player_id ? 'Viewing' : 'View'}</button>
      <button aria-label={`Compare ${p.name}`} disabled={!left || left === p.player_id} aria-pressed={right === p.player_id} onClick={()=>setRight(p.player_id)} className="min-h-11 rounded border border-slate-600 px-3 text-sm disabled:opacity-40">{right === p.player_id ? 'Comparing' : 'Compare'}</button></div>
    </li>)}</ul>
    {!filtered.length && <p className="mt-3 text-sm">No checkpoint players match these filters. This does not establish that a player is unavailable in the NFL or your league.</p>}
    {filtered.length > 20 && <nav aria-label="Player result pages" className="my-3 flex items-center justify-between gap-2 text-sm"><button disabled={page === 0} onClick={()=>setPage(page-1)} className="min-h-11 rounded border border-slate-600 px-3 disabled:opacity-40">Previous players</button><span>Page {page+1} of {Math.ceil(filtered.length/20)}</span><button disabled={(page+1)*20 >= filtered.length} onClick={()=>setPage(page+1)} className="min-h-11 rounded border border-slate-600 px-3 disabled:opacity-40">Next players</button></nav>}
  </section>;
}
