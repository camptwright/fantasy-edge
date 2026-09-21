import Link from "next/link";
import { PageHeader } from "@/components/ui";
import { createApiLoader } from "@/lib/resilient-api";

export const dynamic = "force-dynamic";

type Report = {
  quotes_checked: number; actionable: number; blockers: Record<string, number>;
  roster_corroborated: number; verified_forecast_quotes: number;
  model: { model_version: string; cohort_version: string };
  largest_research_edges: {
    id: string; player_name: string; stat_type: string; source: string; line: number;
    recommendation_blockers: string[]; research_edge_percent: number | null;
    research_under_edge_percent: number | null;
    history_evidence?: { games: number; mean: number; recent_mean: number; last_result_at: string } | null;
    roster_evidence?: { status: string; provider?: string; observed_at?: string };
  }[];
};

export default async function PropValidationPage() {
  const { fetchJson } = createApiLoader();
  const report = await fetchJson<Report | null>("/props/validation", null);
  return <main className="mx-auto max-w-6xl p-4 pb-24 sm:p-6">
    <PageHeader eyebrow="Research audit · not betting recommendations" title="Player-prop validation"
      description="Large model/market disagreements are review signals, not proof of an edge. Model approval, exact event binding and player-team corroboration are checked separately." />
    <Link className="text-blue-300 underline" href="/best-bets">Back to Best Bets</Link>
    {!report ? <p role="alert" className="mt-6 text-amber-300">Validation data is unavailable. No approval status can be inferred; retry shortly.</p> : <>
      <p className="my-6">{report.quotes_checked} fresh quotes checked · {report.actionable} recommendation-eligible.</p>
      <p className="mb-4 text-sm">{report.roster_corroborated} roster-corroborated quotes · {report.verified_forecast_quotes} eligible for verified prospective capture. Football uses a 120-day collection window plus seven grading days; other covered sports use 30 plus seven. At least 200 independent games and passing benchmark tests are still required.</p>
      <p className="mb-4 break-all text-xs text-slate-400">Model: {report.model.model_version}<br />Evidence cohort: {report.model.cohort_version}</p>
      <ul className="mb-6 space-y-1">{Object.entries(report.blockers).map(([reason, count]) =>
        <li key={reason}>{reason.replaceAll("_", " ")}: {count}</li>)}</ul>
      <h2 className="mb-4 text-xl font-semibold">Largest research estimates (up to 40 quotes)</h2>
      <p className="mb-4 text-sm text-amber-300">Historical role averages can be wrong for the upcoming game. Unvalidated estimates are withheld from actionable feeds. Integer lines also require push-aware pricing.</p>
      <div className="space-y-4">{report.largest_research_edges.map(row => <article key={row.id} className="rounded-xl border border-slate-800 p-4">
        <h3 className="font-semibold">{row.player_name} · {row.stat_type.replaceAll("_", " ")} · {row.line} · {row.source}</h3>
        <p className="text-sm">Roster: {row.roster_evidence?.status.replaceAll("_", " ") ?? "unverified"} {row.roster_evidence?.provider ? `(${row.roster_evidence.provider}, observed ${row.roster_evidence.observed_at})` : ""}. Membership does not confirm a starting role.</p>
        <p className="text-sm text-slate-400">Research EV only — over: {row.research_edge_percent?.toFixed(2) ?? "unavailable"}% · under: {row.research_under_edge_percent?.toFixed(2) ?? "unavailable"}%</p>
        {row.history_evidence ? <p className="text-sm">{row.history_evidence.games} historical games · mean {row.history_evidence.mean.toFixed(2)} · recent mean {row.history_evidence.recent_mean.toFixed(2)} · latest result {row.history_evidence.last_result_at.slice(0, 10)}</p> : <p className="text-sm">Insufficient eligible historical support.</p>}
        <p className="mt-2 text-sm text-amber-300">{row.recommendation_blockers.map(reason => reason.replaceAll("_", " ")).join("; ") || "Passed current recommendation gates"}</p>
      </article>)}</div>
    </>}
  </main>;
}
