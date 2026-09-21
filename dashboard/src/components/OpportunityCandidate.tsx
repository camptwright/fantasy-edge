export type OpportunityStat = {stat:string;workload_candidate?:{status:string;mean?:number;usage_stat?:string;expected_usage?:number};workload_evaluation?:{games:number;candidate_mae:number|null;paired_baseline_mae:number|null}};
export type AvailabilityCandidate = {status?:string;shadow_action?:string};
export function OpportunityCandidate({stats,availability}:{stats:OpportunityStat[];availability?:AvailabilityCandidate}) {
 return <details className="my-2 rounded border border-slate-700 p-2 text-xs text-slate-400"><summary>Opportunity / availability · shadow experiments</summary>
  <p>Availability: {(availability?.status||"unverified").replaceAll("_"," ")} · policy: {(availability?.shadow_action||"not captured").replaceAll("_"," ")}. No participation probability is inferred. Estimates remain conditional on playing; this policy does not change serving.</p>
  <p>Workload shrinkage pulls recent five-game usage toward historical usage with eight prior-game equivalents. No automatic promotion.</p>
  {stats.map(s=><p key={s.stat}>{s.stat.replaceAll("_"," ")}: {s.workload_candidate?.status==="ready" ? `${s.workload_candidate.mean?.toFixed(1)} estimate · ${s.workload_candidate.expected_usage?.toFixed(1)} expected ${s.workload_candidate.usage_stat?.replaceAll("_"," ")}`:"insufficient opportunity evidence"}{s.workload_evaluation?.games ? ` · ${s.workload_evaluation.games} paired past-only tests · MAE baseline ${s.workload_evaluation.paired_baseline_mae?.toFixed(2)} / workload ${s.workload_evaluation.candidate_mae?.toFixed(2)}`:""}</p>)}
 </details>;
}
