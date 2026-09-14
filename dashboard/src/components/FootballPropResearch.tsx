export type PropResearch = {
  status: string;
  generated_at?: string;
  seasons: { season: number; scheduled_final_games: number; timeline_passes: number;
    scorer_reconciled_games: number; family_reconciled_games: Record<string, number> }[];
  metrics: { market: string; rows: number; games: number; metric: string;
    control: number; candidate: number }[];
  limitations?: string[];
  promotion_blockers?: string[];
  settlement_rules?: { rules: { id: string; book: string; product: string; status: string;
    source: string; participation: string; unresolved: string[] }[] };
};

export function FootballPropResearch({ data }: { data: PropResearch }) {
  return <section className="mt-10 rounded-xl border border-slate-700 p-5">
    <h2 className="text-xl font-semibold">Football period &amp; scorer research</h2>
    <p className="mt-2 text-sm text-amber-200">Historical research only. Not used by Best Bets. NFL history is reconciled within one provider—not independently validated. NCAAF remains incomplete.</p>
    {data.seasons.length === 0 && <p className="mt-3 text-slate-400">Research results are not available yet.</p>}
    <div className="my-4 grid gap-3 sm:grid-cols-2">{data.seasons.map(s => <div key={s.season} className="rounded-lg bg-slate-900 p-3">
      <h3 className="font-semibold">NFL {s.season}</h3>
      <p>{s.scheduled_final_games} final games · {s.timeline_passes} timeline passes</p>
      <p>{s.scorer_reconciled_games} scorer-reconciled games</p>
      <p className="text-sm text-slate-400">Period families: {Object.entries(s.family_reconciled_games).map(([k,v]) => `${k}: ${v}`).join(" · ")}</p>
    </div>)}</div>
    <details><summary className="cursor-pointer font-medium">Separate 2025 evaluation (2024 warm-up)</summary>
      <p className="my-2 text-sm text-slate-400">Control: previous 20 eligible games. Candidate: previous 8. Lower error is better. These are not production-baseline or betting-return comparisons. Population is conditional on recorded participation.</p>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Market</th><th>Games</th><th>Metric</th><th>Control</th><th>Candidate</th></tr></thead>
        <tbody>{data.metrics.map(m => <tr key={m.market} className="border-t border-slate-800"><td className="py-2">{m.market}</td><td>{m.games}</td><td>{m.metric}</td><td>{m.control.toFixed(4)}</td><td>{m.candidate.toFixed(4)}</td></tr>)}</tbody></table></div>
    </details>
    <details className="mt-4"><summary className="cursor-pointer font-medium">Settlement evidence &amp; remaining requirements</summary>
      {data.settlement_rules?.rules.map(r => <div key={r.id} className="mt-3 text-sm"><a className="text-cyan-300 underline" href={r.source} target="_blank" rel="noreferrer">{r.book} / {r.product}</a><p>{r.status}: {r.participation.replaceAll("_", " ")}</p><p className="text-slate-400">Unresolved: {r.unresolved.join(", ").replaceAll("_", " ")}</p></div>)}
      {data.limitations?.map(x => <p key={x} className="mt-2 text-sm text-slate-400">{x}</p>)}
      <p className="mt-3 text-sm text-amber-200">Promotion blockers: {data.promotion_blockers?.join(", ").replaceAll("_", " ") || "Evidence not loaded"}</p>
    </details>
  </section>;
}
