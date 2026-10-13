"use client";
import { useState } from "react";
import { playerProfileHref, pts, type Overview } from "@/lib/workspace";
import type { PlayerDetail } from "@/lib/workspace-api.generated";

const POSITIONS = ["QB", "RB", "WR", "TE"] as const;
const SHOW = 8;
type Basis = "ros" | "week";

const value = (p: PlayerDetail, basis: Basis) => basis === "ros" ? p.engine_ros_points : (p.consensus_week_points ?? p.engine_week_points ?? p.points);

/**
 * FantasyPros Waiver Central-style position ladder: your players and available
 * free agents in one ranked list per position, with each player's league-wide
 * positional rank, so you see exactly which adds outrank whom.
 */
export function WorkspacePositionLadder({ overview }: { overview: Overview }) {
  const [basis, setBasis] = useState<Basis>("ros");
  const strength = new Map(overview.strength.positions.map(p => [p.position, p]));
  return <section aria-label="Position ladder" className="mt-6">
    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
      <h2 className="text-lg font-semibold">Position ladder</h2>
      <div role="group" aria-label="Ranking basis" className="flex rounded-lg border border-slate-700 p-0.5 text-xs">
        {([["ros", "Rest of season"], ["week", `Week ${overview.week ?? "?"}`]] as const).map(([id, label]) =>
          <button key={id} type="button" aria-pressed={basis === id} onClick={() => setBasis(id)}
            className={`min-h-9 rounded-md px-3 ${basis === id ? "bg-slate-700 text-white" : "text-slate-400"}`}>{label}</button>)}
      </div>
    </div>
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{POSITIONS.map(pos => {
      const all = overview.comparison_players.filter(p => p.position === pos && value(p, basis) != null)
        .sort((a, b) => (value(b, basis) ?? 0) - (value(a, basis) ?? 0));
      const rank = new Map(all.map((p, i) => [p.player_id, i + 1]));
      const rows = all.filter(p => p.ownership === "your_roster" || p.ownership === "unrostered_snapshot").slice(0, SHOW);
      const s = strength.get(pos);
      return <div key={pos} className="rounded-xl border border-slate-800 bg-slate-900/50 p-3">
        <h3 className="flex items-center justify-between text-sm font-semibold">{pos}
          {s?.rank != null && <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[11px] font-normal text-slate-300">Your rank {s.rank} of {s.teams}</span>}</h3>
        {!rows.length ? <p className="mt-2 text-xs text-slate-500">No ranked players (engine research missing).</p> :
        <ol className="mt-2 space-y-1 text-sm">{rows.map(p => {
          const mine = p.ownership === "your_roster";
          return <li key={p.player_id} className={`flex items-center gap-2 rounded-md px-2 ${mine ? "bg-sky-500/10" : "bg-emerald-500/5"}`}>
            <span className="w-8 text-right text-[11px] tabular-nums text-slate-500">{pos}{rank.get(p.player_id)}</span>
            <a href={playerProfileHref(overview.league_id, p.player_id)} className="min-w-0 flex-1 truncate hover:underline">{p.name}</a>
            <span className="text-[11px] tabular-nums text-slate-400">{pts(value(p, basis))}</span>
            {(basis === "ros" ? p.sos_ros_stars : p.sos_next4_stars) != null && <span aria-label={`Schedule ${(basis === "ros" ? p.sos_ros_stars : p.sos_next4_stars)} of 5 stars, 5 is easiest`} className="text-[10px] tabular-nums text-amber-300">{basis === "ros" ? p.sos_ros_stars : p.sos_next4_stars}★</span>}
            <span className={`w-14 text-right text-[10px] uppercase tracking-wider ${mine ? "text-sky-300" : "text-emerald-300"}`}>{mine ? "Yours" : "Available"}</span>
          </li>;
        })}</ol>}
      </div>;
    })}</div>
    <p className="mt-2 text-xs text-slate-500">Ranks are among every player at the position in this league{basis === "ros" ? " by engine rest-of-season points (research)" : " by this week’s consensus, else the engine, else the provider"}. ★ = strength of schedule (5 easiest; rest of season or the next four games). Available means unrostered in this snapshot; confirm on your platform.</p>
  </section>;
}
