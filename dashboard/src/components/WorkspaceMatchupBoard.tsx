"use client";
import { useState } from "react";
import { pct, playerProfileHref, pts } from "@/lib/workspace";
import type { AccuracyWeek, MatchupSide, Starter } from "@/lib/workspace-api.generated";

const CHIP: Record<string, string> = { QB: "bg-rose-400/20 text-rose-200", RB: "bg-sky-400/20 text-sky-200", WR: "bg-emerald-400/20 text-emerald-200",
  TE: "bg-amber-400/20 text-amber-200", K: "bg-violet-400/20 text-violet-200", DEF: "bg-slate-500/30 text-slate-200" };

function Cell({ s, align, league }: { s?: Starter; align: "left" | "right"; league: string }) {
  if (!s) return <div />;
  const beat = s.recorded_points != null && s.points != null && s.recorded_points > 0 ? s.recorded_points >= s.points : null;
  const right = align === "right";
  return <div className={`flex min-w-0 items-center gap-2 ${right ? "flex-row-reverse text-right" : ""}`}>
    <div className="min-w-0 flex-1">
      {s.player_id ? <a href={playerProfileHref(league, s.player_id)} className="block truncate text-sm hover:underline">{s.name}</a> : <span className="block truncate text-sm text-slate-500">{s.name}</span>}
      <span className="text-[11px] text-slate-500">{s.position ?? ""}{s.locked ? " · locked" : ""}</span>
    </div>
    <div className={`shrink-0 tabular-nums ${right ? "text-left" : "text-right"}`}>
      <span className="block text-base font-semibold">{pts(s.recorded_points)}</span>
      <span className={`block text-[11px] ${beat == null ? "text-slate-500" : beat ? "text-emerald-300" : "text-rose-300"}`}>{pts(s.points)}</span>
    </div>
  </div>;
}

/** FantasyPros-style head-to-head: slot by slot, recorded points over projection, current vs hindsight-optimal. */
export function WorkspaceMatchupBoard({ mine, opponent, league, season }: { mine: MatchupSide | null; opponent: MatchupSide | null; league: string; season: AccuracyWeek[] }) {
  const [view, setView] = useState<"current" | "optimal">("current");
  const left = view === "optimal" && mine?.optimal.length ? mine.optimal : mine?.starters ?? [];
  const right = view === "optimal" && opponent?.optimal.length ? opponent.optimal : opponent?.starters ?? [];
  const rows = Math.max(left.length, right.length);
  const seasonAvg = season.length ? season.reduce((a, w) => a + w.accuracy, 0) / season.length : null;
  return <div className="border-t border-slate-800 px-5 py-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-sm font-semibold">Starters</h3>
      <div role="group" aria-label="Lineup view" className="flex rounded-lg border border-slate-700 p-0.5 text-xs">
        {(["current", "optimal"] as const).map(v => <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}
          className={`min-h-9 rounded-md px-3 capitalize ${view === v ? "bg-slate-700 text-white" : "text-slate-400"}`}>{v === "optimal" ? "Optimal (hindsight)" : "Current"}</button>)}
      </div>
    </div>
    <ol className="mt-3 space-y-1">{Array.from({ length: rows }, (_, i) => {
      const slot = left[i]?.slot ?? right[i]?.slot ?? "";
      return <li key={i} className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 rounded-lg bg-slate-900/60 px-3 py-2">
        <Cell s={left[i]} align="left" league={league} />
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${CHIP[slot] ?? "bg-gradient-to-r from-sky-400/20 to-emerald-400/20 text-slate-200"}`}>{slot.replace("SUPER_FLEX", "SF").replace("REC_FLEX", "RFX")}</span>
        <Cell s={right[i]} align="right" league={league} />
      </li>;
    })}</ol>
    <p className="mt-2 text-[11px] text-slate-500">Big number: recorded points so far · small: pregame projection (green beat it, red missed). Optimal is the best lineup in hindsight from each roster’s recorded points.</p>
    <dl className="mt-3 grid grid-cols-2 gap-3 text-xs sm:grid-cols-3">
      <div><dt className="text-slate-500">Your start/sit accuracy (week)</dt><dd className="text-base font-semibold tabular-nums">{mine?.start_sit_accuracy != null ? pct(Math.min(1, mine.start_sit_accuracy)) : "—"}</dd></div>
      <div><dt className="text-slate-500">Season average</dt><dd className="text-base font-semibold tabular-nums">{seasonAvg != null ? pct(seasonAvg) : "—"}</dd></div>
      <div className="col-span-2 sm:col-span-1"><dt className="text-slate-500">Points left on bench (season)</dt><dd className="text-base font-semibold tabular-nums">{season.length ? season.reduce((a, w) => a + (w.optimal - w.actual), 0).toFixed(1) : "—"}</dd></div>
    </dl>
  </div>;
}
