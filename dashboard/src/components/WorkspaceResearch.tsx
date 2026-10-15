import { fantasyApi } from "@/lib/fantasy-api";
import type { EngineQualification, QualificationTrack } from "@/lib/workspace-api.generated";

type Calibration = { reports: { sport: string; market: string; sample_size: number; brier_score: number | null; passed_gate: boolean; evaluated_at: string }[] };
type Evaluation = { status: string; operationally_fresh?: boolean; completed_today_utc?: boolean };
type Governance = { status: string; review?: { forecast_count?: number; reviewed_at?: string } };

const label = (s: string) => s.replaceAll("_", " ");

function Progress({ track }: { track: QualificationTrack }) {
  const retrospective = track.evidence_type === 'retrospective_reconstructed_current_weights';
  const historical = track.evidence_type === 'historical_older_version';
  const pct = Math.min(100, (track.graded_weeks / Math.max(1, track.required_weeks)) * 100);
  const d = track.pool.paired_difference;
  return <li className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h3 className="font-semibold">{track.name}</h3>
      <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider ${track.eligible_for_owner_review ? "bg-emerald-400 text-slate-950" : "bg-slate-800 text-slate-300"}`}>{track.eligible_for_owner_review ? "Ready for owner review" : "Not promoted"}</span>
    </div>
    <p className="mt-2 text-xs text-slate-400">{retrospective?'Retrospective reconstruction · weights were not frozen with forecasts':historical?'Historical report · earlier model version':track.current_version?'Current model · forecasts frozen before kickoff':'Current-version report unavailable'}</p>
    <p className="mt-3 flex justify-between text-xs text-slate-400"><span>{retrospective||historical?'Observed graded weeks':'Qualification weeks'}</span><span className="tabular-nums">{track.graded_weeks}{!retrospective&&!historical?` / ${track.required_weeks}`:''}</span></p>
    {!retrospective&&!historical&&<span aria-hidden="true" className="mt-1 block h-2 rounded bg-slate-800"><span className="block h-2 rounded bg-sky-400" style={{ width: `${pct}%` }} /></span>}
    <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
      <div><dt className="text-[11px] text-slate-500">Engine MAE</dt><dd className="tabular-nums">{track.pool.engine_mae?.toFixed(2) ?? "—"}</dd></div>
      <div><dt className="text-[11px] text-slate-500">Sleeper MAE</dt><dd className="tabular-nums">{track.pool.sleeper_mae?.toFixed(2) ?? "—"}</dd></div>
      <div><dt className="text-[11px] text-slate-500">Paired diff</dt><dd className={`tabular-nums ${d == null ? "" : d < 0 ? "text-emerald-300" : "text-rose-300"}`}>{d == null ? "—" : `${d > 0 ? "+" : ""}${d.toFixed(2)}`}</dd></div>
    </dl>
    <p className="mt-2 text-[11px] text-slate-500">{track.status === "no_report_yet" ? "No prospective report yet." : `${track.pool.n} paired starter-pool rows${track.pool.ci ? ` · 95% CI ${track.pool.ci.map(v => v.toFixed(2)).join(" to ")}` : ""}${track.engine_forecasts != null ? ` · ${track.engine_forecasts} frozen engine forecasts` : ""}`}</p>
    {!!track.blockers.length && <p className="mt-1 text-[11px] text-amber-200/80">Blockers: {track.blockers.map(label).join(" · ")}</p>}
    {(Object.keys(track.by_position??{}).length>0||(track.by_week??[]).length>0)&&<details className="mt-3 text-xs"><summary className="cursor-pointer text-slate-300">Position and week evidence</summary>
      <dl className="mt-2 space-y-1">{Object.entries(track.by_position??{}).map(([position,s])=><div key={position} className="flex justify-between gap-2"><dt>{position}</dt><dd>{s.n} pairs · {s.independent_weeks||s.weeks.length} weeks · MAE {s.engine_mae?.toFixed(2)??'—'} vs {s.sleeper_mae?.toFixed(2)??'—'}</dd></div>)}</dl>
      <ul className="mt-2 space-y-1">{(track.by_week??[]).map(w=><li key={`${w.season}:${w.week}`}>{w.season??''} week {w.week}: {w.n} pairs{Object.entries(w.positions).filter(([,s])=>s.n>0).map(([p,s])=>` · ${p} ${s.n}`).join('')}</li>)}</ul>
    </details>}
  </li>;
}

/** Native Research summary: fantasy engine qualification, calibration gates and lab governance. */
export async function WorkspaceResearch() {
  const [engine, calibration, evaluation, governance] = await Promise.all([
    fantasyApi<EngineQualification>("/api/v2/fantasy/engine-qualification", 5000), fantasyApi<Calibration>("/calibration", 5000),
    fantasyApi<Evaluation>("/calibration/evaluation-status", 5000), fantasyApi<Governance>("/experiments/nfl-predictor/governance", 5000)]);
  const passed = calibration?.reports.filter(r => r.passed_gate).length;
  return <div className="space-y-8">
    <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {([["Calibration gates passed", calibration ? `${passed} / ${calibration.reports.length}` : "—", "Walk-forward backtests by sport and market"],
        ["Daily evaluation", evaluation ? label(evaluation.status) : "—", evaluation ? (evaluation.operationally_fresh ? "Fresh today" : "Not fresh") : "Status unavailable"],
        ["NFL lab forecasts", governance?.review?.forecast_count != null ? String(governance.review.forecast_count) : "—", governance ? label(governance.status) : "Governance unavailable"],
        ["Fantasy engine", engine ? (engine.tracks.some(t => t.eligible_for_owner_review) ? "Review ready" : "Research only") : "—", "Sleeper projections remain the decision baseline"]] as const).map(([k, v, sub]) =>
        <div key={k} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4"><dt className="text-xs text-slate-400">{k}</dt><dd className="mt-1 text-xl font-semibold capitalize tabular-nums">{v}</dd><dd className="mt-1 text-[11px] text-slate-500">{sub}</dd></div>)}
    </dl>
    <section aria-label="Fantasy engine qualification">
      <h2 className="text-lg font-semibold">Fantasy projection qualification</h2>
      <p className="mt-1 text-xs text-slate-500">{engine?.note ?? "Qualification service unavailable. This is a connection error, not a failed model."}</p>
      {engine && <ul className="mt-3 grid gap-3 md:grid-cols-3">{engine.tracks.map(t => <Progress key={t.name} track={t} />)}</ul>}
    </section>
    {engine && <section aria-label="Win probability check" className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <h2 className="font-semibold">Matchup win probability · prospective check</h2>
      <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div><dt className="text-[11px] text-slate-500">Graded matchups</dt><dd className="text-lg font-semibold tabular-nums">{engine.win_probability.graded}</dd></div>
        <div><dt className="text-[11px] text-slate-500">Captured (pregame)</dt><dd className="text-lg font-semibold tabular-nums">{engine.win_probability.captured_matchups}</dd></div>
        <div><dt className="text-[11px] text-slate-500">Brier (lower is better)</dt><dd className={`text-lg font-semibold tabular-nums ${engine.win_probability.brier == null ? "" : engine.win_probability.brier < engine.win_probability.coin_flip_brier ? "text-emerald-300" : "text-rose-300"}`}>{engine.win_probability.brier?.toFixed(3) ?? "—"}</dd></div>
        <div><dt className="text-[11px] text-slate-500">Coin flip</dt><dd className="text-lg font-semibold tabular-nums">{engine.win_probability.coin_flip_brier.toFixed(3)}</dd></div>
      </dl>
      <p className="mt-2 text-[11px] text-slate-500">The latest win probability frozen before any starter’s game kicks off, graded once the NFL week is final. {engine.win_probability.status === "no_report_yet" ? "No report yet." : Object.entries(engine.win_probability.statuses).map(([k, v]) => `${label(k)}: ${v}`).join(" · ")} The fit-time check was 24 past matchups (Brier 0.223); this sample grows every week.</p>
    </section>}
    <section aria-label="Calibration gates">
      <h2 className="text-lg font-semibold">Market model calibration</h2>
      {!calibration ? <p role="status" className="mt-2 rounded-xl border border-amber-800 p-4 text-sm">Calibration service unavailable.</p> :
      <div className="workspace-scrollbar mt-3 overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full min-w-[32rem] text-sm">
          <thead className="bg-slate-900/70 text-xs text-slate-400"><tr>{["Sport", "Market", "Sample", "Brier", "Gate"].map((h, i) => <th key={h} scope="col" className={`px-3 py-2 font-medium ${i >= 2 && i <= 3 ? "text-right" : "text-left"}`}>{h}</th>)}</tr></thead>
          <tbody>{calibration.reports.map(r => <tr key={`${r.sport}:${r.market}`} className="border-t border-slate-800/70">
            <td className="px-3 py-2 uppercase">{r.sport}</td><td className="px-3 py-2 capitalize">{r.market}</td>
            <td className="px-3 py-2 text-right tabular-nums">{r.sample_size}</td><td className="px-3 py-2 text-right tabular-nums">{r.brier_score?.toFixed(3) ?? "—"}</td>
            <td className="px-3 py-2">{r.passed_gate ? <span className="text-emerald-300">Passed</span> : <span className="text-slate-400">Not passed</span>}</td>
          </tr>)}</tbody>
        </table>
      </div>}
    </section>
  </div>;
}
