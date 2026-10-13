import { fantasyToolHref, pts } from "@/lib/workspace";
import type { Recap, RecapGame } from "@/lib/workspace-api.generated";

/** Your weekly points against the league median (FantasyPros' "Weekly Points" chart). */
export function WeeklyPointsChart({ weeks, mine, median }: { weeks: number[]; mine: number[]; median: number[] }) {
  if (weeks.length < 2) return <p className="text-sm text-slate-400">The chart needs two completed weeks.</p>;
  const w = 560, h = 180, pad = 28;
  const lo = Math.min(...mine, ...median) * 0.9, hi = Math.max(...mine, ...median) * 1.05;
  const x = (i: number) => pad + (i * (w - 2 * pad)) / (weeks.length - 1);
  const y = (v: number) => h - pad - ((v - lo) / (hi - lo || 1)) * (h - 2 * pad);
  const path = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  return <figure>
    <svg viewBox={`0 0 ${w} ${h}`} className="block w-full max-w-2xl" role="img" aria-label={`Your points vs league median over weeks ${weeks[0]} to ${weeks.at(-1)}`}>
      <path d={`${path(mine)} L${x(mine.length - 1)},${h - pad} L${x(0)},${h - pad} Z`} fill="#34d399" opacity="0.12" />
      <path d={path(median)} fill="none" stroke="#94a3b8" strokeWidth="2" strokeDasharray="5 5" />
      <path d={path(mine)} fill="none" stroke="#34d399" strokeWidth="2.5" />
      {mine.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r="3.5" fill={v >= median[i] ? "#34d399" : "#fb7185"} />)}
      {weeks.map((wk, i) => <text key={wk} x={x(i)} y={h - 8} textAnchor="middle" fontSize="11" fill="#64748b">Wk {wk}</text>)}
    </svg>
    <figcaption className="mt-1 flex gap-4 text-xs text-slate-400"><span className="text-emerald-300">— You</span><span>- - League median</span><span>Dots: red = below median</span></figcaption>
  </figure>;
}

const game = (g: RecapGame | null | undefined) => g ? `${g.home} ${g.home_points.toFixed(1)} – ${g.away_points.toFixed(1)} ${g.away}` : "—";

/** FantasyPros' "The Post-Game": weekly recap and season-to-date. */
export function WorkspaceRecap({ recap, league }: { recap: Recap | null; league: string }) {
  if (!recap) return <p role="status" className="rounded-xl border border-amber-800 p-4 text-sm">Recap unavailable. This is a service error.</p>;
  if (recap.status !== "available" || !recap.week) return <p role="status" className="rounded-xl border border-slate-800 p-4 text-sm text-slate-400">No recap yet ({recap.status.replaceAll("_", " ")}).</p>;
  const w = recap.week, s = recap.season;
  const banner = w.result === "W" ? "bg-emerald-500/15 text-emerald-200" : w.result === "L" ? "bg-rose-500/15 text-rose-200" : "bg-slate-800 text-slate-200";
  return <div className="space-y-6">
    <nav aria-label="Recap week" className="workspace-scrollbar flex gap-2 overflow-x-auto">{recap.completed_weeks.map(n => <a key={n} href={`${fantasyToolHref("recap", league)}&week=${n}`} aria-current={n === w.week ? "page" : undefined}
      className={`flex min-h-10 shrink-0 items-center rounded-full border px-4 text-sm ${n === w.week ? "border-emerald-500 bg-emerald-500/10 text-emerald-200" : "border-slate-700 text-slate-300"}`}>Week {n}</a>)}</nav>
    <section aria-label="Weekly recap" className="rounded-2xl border border-slate-800 p-5">
      <p className={`inline-block rounded-full px-3 py-1 text-sm font-semibold ${banner}`}>{w.result === "W" ? "Win" : w.result === "L" ? "Loss" : w.result === "T" ? "Tie" : "No opponent"} · {w.points.toFixed(1)}{w.opponent_points != null ? ` – ${w.opponent_points.toFixed(1)} vs ${w.opponent}` : ""}</p>
      <dl className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {([["League rank", `${w.score_rank} of ${w.teams}`, "by points this week"], ["All-play", `${w.all_play_wins}–${w.all_play_losses}`, "vs every team this week"],
          ["League median", w.league_median.toFixed(1), `${w.points >= w.league_median ? "+" : ""}${(w.points - w.league_median).toFixed(1)} for you`],
          ["Left on bench", pts(w.bench_points_left), "vs your best possible lineup"]] as const).map(([k, v, sub]) =>
          <div key={k} className="rounded-xl border border-slate-800 bg-slate-900/60 p-3"><dt className="text-xs text-slate-400">{k}</dt><dd className="mt-1 text-xl font-semibold tabular-nums">{v}</dd><dd className="text-[11px] text-slate-500">{sub}</dd></div>)}
      </dl>
      <ul className="mt-4 space-y-1 text-sm text-slate-300">
        {w.top_scorer && <li>Top scorer: <strong>{w.top_scorer}</strong> with {pts(w.top_scorer_points)}.</li>}
        {w.best_bench && w.best_bench_points != null && w.best_bench_points > 0 && <li>Best on your bench: <strong>{w.best_bench}</strong> with {pts(w.best_bench_points)}.</li>}
        <li>League high: {game(w.high_score)} · Closest: {game(w.closest_game)} · Biggest blowout: {game(w.biggest_blowout)}{w.low_team ? ` · Low score: ${w.low_team} ${pts(w.low_points)}` : ""}.</li>
      </ul>
    </section>
    <section aria-label="Season to date" className="rounded-2xl border border-slate-800 p-5">
      <h2 className="font-semibold">Season to date</h2>
      <dl className="mt-3 grid grid-cols-3 gap-3 text-sm">
        <div><dt className="text-xs text-slate-400">All-play record</dt><dd className="text-lg font-semibold tabular-nums">{s.all_play_wins}–{s.all_play_losses}</dd></div>
        <div><dt className="text-xs text-slate-400">Wins vs expected</dt><dd className="text-lg font-semibold tabular-nums">{s.wins} vs {s.expected_wins?.toFixed(1) ?? "—"}</dd></div>
        <div><dt className="text-xs text-slate-400">Luck</dt><dd className={`text-lg font-semibold tabular-nums ${s.luck == null ? "" : s.luck >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{s.luck == null ? "—" : `${s.luck >= 0 ? "+" : ""}${s.luck.toFixed(1)} wins`}</dd></div>
      </dl>
      <div className="mt-4"><WeeklyPointsChart weeks={s.weeks} mine={s.my_points} median={s.median_points} /></div>
      <p className="mt-2 text-xs text-slate-500">{recap.note}</p>
    </section>
  </div>;
}
