"use client";
import { useState } from "react";
import { pct, playerProfileHref, pts, type Overview } from "@/lib/workspace";
import type { PlayerDetail } from "@/lib/workspace-api.generated";
import { DistributionCurve, Meter } from "./OutcomeCharts";
import { playOdds } from "./WorkspaceAreTheyPlaying";

export const BOOM_BUST: Record<string, [number, number]> = { QB: [25, 12], RB: [20, 6], WR: [20, 6], TE: [15, 4], K: [12, 4], DEF: [12, 2] };
const COLORS = ["#34d399", "#60a5fa", "#f59e0b", "#e879f9"];
const MAX_COMPARE = 4;

/** WalterPicks-style "Who do I start?" from the saved simulation; research only. */
export function WorkspaceStartSit({ overview }: { overview: Overview }) {
  const ranges = overview.outcomes.player_ranges;
  const players = [...overview.roster_players].sort((a, b) => (ranges[b.player_id]?.mean ?? b.points ?? -1) - (ranges[a.player_id]?.mean ?? a.points ?? -1));
  const [ids, setIds] = useState<string[]>([players[0]?.player_id ?? "", players[1]?.player_id ?? ""]);
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
      <div className={`mt-4 grid gap-3 ${ids.length > 2 ? "sm:grid-cols-2 lg:grid-cols-4" : "sm:grid-cols-2"}`}>{ids.map((id, i) => <div key={i} className="text-xs text-slate-400">
        <label>Player {i + 1}
        <select value={id} onChange={e => setIds(ids.map((v, j) => j === i ? e.target.value : v))}
          className="mt-1 block min-h-11 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100" style={{ borderColor: COLORS[i] }}>
          {players.map(p => <option key={p.player_id} value={p.player_id}>{p.name} · {p.position} · {p.team ?? "FA"}</option>)}
        </select></label>
        {ids.length > 2 && <button type="button" onClick={() => setIds(ids.filter((_, j) => j !== i))} className="mt-1 min-h-9 text-xs text-slate-500 underline">Remove</button>}
      </div>)}</div>
      {ids.length < MAX_COMPARE && <button type="button" onClick={() => setIds([...ids, players.find(p => !ids.includes(p.player_id))?.player_id ?? ""])}
        className="mt-3 min-h-11 rounded-lg border border-slate-700 px-3 text-sm hover:border-emerald-500">+ Compare another player</button>}
      {chosen.length >= 2 && <>
        <h3 className="mt-6 text-center text-sm font-semibold">Week {overview.week ?? "?"} projection</h3>
        <div className={`mt-2 grid gap-2 ${chosen.length > 2 ? "grid-cols-1" : "grid-cols-2"}`}>{chosen.map((p, i) => {
          const mean = ranges[p.player_id]?.mean ?? p.points;
          const win = mean != null && chosen.every(o => (ranges[o.player_id]?.mean ?? o.points ?? -1) <= mean);
          const left = chosen.length === 2 && !i;
          return <div key={p.player_id} className={left ? "flex justify-end" : ""}>
            {chosen.length > 2 && <p className="mb-0.5 text-xs" style={{ color: COLORS[i] }}>{p.name}</p>}
            <div className={`flex h-10 items-center rounded px-3 text-sm font-semibold tabular-nums ${win ? "bg-emerald-500 text-slate-950" : "bg-slate-700 text-slate-100"} ${left ? "justify-end" : ""}`} style={{ width: `${Math.max(18, ((mean ?? 0) / top) * 100)}%` }}>{pts(mean)}</div>
          </div>;
        })}</div>
        <dl className={`mt-4 grid gap-4 text-sm ${chosen.length > 2 ? "sm:grid-cols-2" : "grid-cols-2"}`}>{chosen.map((p, i) => {
          const r = ranges[p.player_id];
          const left = chosen.length === 2 && !i;
          return <div key={p.player_id} className={left ? "text-right" : ""}>
            <dt className="font-medium" style={{ color: COLORS[i] }}><a href={playerProfileHref(overview.league_id, p.player_id)} className="hover:underline">{p.name}</a></dt>
            <dd className="mt-1 text-xs text-slate-400">Range {pts(r?.p10)}–{pts(r?.p90)} · consensus {pts(p.consensus_week_points)} · engine {pts(p.engine_week_points)} · {r?.basis?.replaceAll("_", " ") ?? "not simulated"}</dd>
            {p.play_probability != null && <dd className="mt-1 text-xs text-amber-200">{p.injury_status}: {playOdds(p)} · risk-adjusted {pts(((r?.mean ?? p.points) ?? 0) * p.play_probability)}</dd>}
            <dd className={`mt-1 flex items-center gap-2 text-xs text-slate-400 ${left ? "justify-end" : ""}`}>Boom <Meter probability={r?.boom_probability} tone="up" label="Boom" /> Bust <Meter probability={r?.bust_probability} tone="down" label="Bust" /></dd>
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
