"use client";
import { useState } from "react";
import { pct, playerProfileHref, pts, type Overview } from "@/lib/workspace";
import type { PlayerDetail } from "@/lib/workspace-api.generated";
import { DistributionCurve, Meter } from "./OutcomeCharts";

export const BOOM_BUST: Record<string, [number, number]> = { QB: [25, 12], RB: [20, 6], WR: [20, 6], TE: [15, 4], K: [12, 4], DEF: [12, 2] };
const COLORS = ["#34d399", "#60a5fa"];

/** WalterPicks-style "Who do I start?" from the saved simulation; research only. */
export function WorkspaceStartSit({ overview }: { overview: Overview }) {
  const ranges = overview.outcomes.player_ranges;
  const players = [...overview.roster_players].sort((a, b) => (ranges[b.player_id]?.mean ?? b.points ?? -1) - (ranges[a.player_id]?.mean ?? a.points ?? -1));
  const [ids, setIds] = useState<[string, string]>([players[0]?.player_id ?? "", players[1]?.player_id ?? ""]);
  const chosen = ids.map(id => players.find(p => p.player_id === id)).filter((p): p is PlayerDetail => !!p);
  const withRange = chosen.filter(p => ranges[p.player_id]?.density.length);
  const [boom, bust] = BOOM_BUST[chosen[0]?.position ?? ""] ?? [20, 6];
  const best = overview.outcomes;
  const top = Math.max(1, ...chosen.map(p => ranges[p.player_id]?.mean ?? p.points ?? 0));
  return <div className="space-y-6">
    <section aria-label="Lineup win probability" className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <h2 className="font-semibold">Max-win lineup <span className="ml-1 rounded bg-sky-500/15 px-2 py-0.5 align-middle text-[11px] font-medium uppercase tracking-wider text-sky-300">Simulation research</span></h2>
      {best.status !== "estimated_research" ? <p role="status" className="mt-2 text-sm text-slate-400">Withheld: {best.reason.replaceAll("_", " ")}{best.blockers.length ? ` — ${best.blockers.slice(0, 3).join("; ")}${best.blockers.length > 3 ? "…" : ""}` : ""}. No win probability is shown rather than a guess.</p> : <>
        <p className="mt-2 text-sm text-slate-300">Current lineup wins <strong className="tabular-nums">{pct(best.win_probability)}</strong> of simulations{best.best_win_probability != null && best.best_changes.length ? <>; the best lineup found wins <strong className="tabular-nums text-emerald-300">{pct(best.best_win_probability)}</strong>.</> : <>; no lineup found that wins more often.</>}</p>
        {!!best.best_changes.length && <ul className="mt-3 space-y-1 text-sm">{best.best_changes.map(c => <li key={c.slot + c.start}><span className="text-slate-500">{c.slot}:</span> start <a className="text-emerald-300 hover:underline" href={playerProfileHref(overview.league_id, c.start)}>{c.start_name}</a> over {c.replaces_name}</li>)}</ul>}
        <p className="mt-3 text-xs text-slate-500">Chosen on one half of {best.validation_matchups != null ? "the" : ""} simulated draws, reported on the other. Held-out check: Brier {best.validation_brier ?? "—"} over {best.validation_matchups ?? 0} past matchups vs {best.coin_flip_brier ?? "—"} for a coin flip — a small sample, not validation.</p>
      </>}
    </section>
    <section aria-label="Who do I start" className="rounded-2xl border border-slate-800 p-5">
      <h2 className="text-center text-xl font-semibold">Who do I start?</h2>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">{[0, 1].map(i => <label key={i} className="text-xs text-slate-400">Player {i + 1}
        <select value={ids[i]} onChange={e => setIds(i ? [ids[0], e.target.value] : [e.target.value, ids[1]])}
          className="mt-1 block min-h-11 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100" style={{ borderColor: COLORS[i] }}>
          {players.map(p => <option key={p.player_id} value={p.player_id}>{p.name} · {p.position} · {p.team ?? "FA"}</option>)}
        </select></label>)}</div>
      {chosen.length === 2 && <>
        <h3 className="mt-6 text-center text-sm font-semibold">Week {overview.week ?? "?"} projection</h3>
        <div className="mt-2 grid grid-cols-2 gap-2">{chosen.map((p, i) => {
          const mean = ranges[p.player_id]?.mean ?? p.points;
          const win = mean != null && chosen.every(o => (ranges[o.player_id]?.mean ?? o.points ?? -1) <= mean);
          return <div key={p.player_id} className={i ? "" : "flex justify-end"}>
            <div className={`flex h-10 items-center rounded px-3 text-sm font-semibold tabular-nums ${win ? "bg-emerald-500 text-slate-950" : "bg-slate-700 text-slate-100"} ${i ? "" : "justify-end"}`} style={{ width: `${Math.max(18, ((mean ?? 0) / top) * 100)}%` }}>{pts(mean)}</div>
          </div>;
        })}</div>
        <dl className="mt-4 grid grid-cols-2 gap-4 text-sm">{chosen.map((p, i) => {
          const r = ranges[p.player_id];
          return <div key={p.player_id} className={i ? "" : "text-right"}>
            <dt className="font-medium" style={{ color: COLORS[i] }}><a href={playerProfileHref(overview.league_id, p.player_id)} className="hover:underline">{p.name}</a></dt>
            <dd className="mt-1 text-xs text-slate-400">Range {pts(r?.p10)}–{pts(r?.p90)} · engine {pts(p.engine_week_points)} · {r?.basis?.replaceAll("_", " ") ?? "not simulated"}</dd>
            <dd className={`mt-1 flex items-center gap-2 text-xs text-slate-400 ${i ? "" : "justify-end"}`}>Boom <Meter probability={r?.boom_probability} tone="up" label="Boom" /> Bust <Meter probability={r?.bust_probability} tone="down" label="Bust" /></dd>
          </div>;
        })}</dl>
        <h3 className="mt-6 text-sm font-semibold">Boom/bust probability</h3>
        {withRange.length ? <DistributionCurve ranges={withRange.map(p => ({ label: p.name, range: ranges[p.player_id] }))} colors={withRange.map(p => COLORS[chosen.indexOf(p)])} boom={boom} bust={bust} />
          : <p className="mt-2 text-sm text-slate-400">No simulated distribution for these players in this snapshot (the simulation is withheld, the game has started, or no fresh projection). Missing is not zero.</p>}
        <p className="mt-2 text-xs text-slate-500">Distributions come from graded past projection errors by position and projection size; boom/bust thresholds use {chosen[0]?.position} cut-offs ({bust} / {boom} points). Mean is the provider projection{best.blend_status?.startsWith("applied") ? " blended with the engine" : " (the engine blend did not beat it out of sample, so it is not applied)"}.</p>
      </>}
    </section>
  </div>;
}
