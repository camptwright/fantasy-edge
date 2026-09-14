import { PageHeader, SportBadge, MarketBadge } from "@/components/ui";

// Static generation happens during the image build, before the API and its
// database are available - same reasoning as the Board/Recommendations pages.
export const dynamic = "force-dynamic";

type PropReadiness = { research_at: string | null; note: string; families: {
  stat_type: string; status: string; reason: string; quotes: number;
  qualified_quotes: number; historical_rows: number; historical_games: number;
}[] };

type ContextReadiness = { latest_capture_at: string | null; player_forecasts: number; note: string; inputs: {
  name: string; status: string; note: string; forecast_records_with_evidence?: number; headline_references?: number; report_records?: number;
}[] };

type CalibrationReport = {
  sport: string;
  market: string;
  seasons_used: number[];
  sample_size: number;
  brier_score: number | null;
  log_loss: number | null;
  passed_gate: boolean;
  evaluated_at: string;
};

function apiUrl(): string {
  return process.env.FANTASY_API_URL || "http://api:8000";
}

type LiveReport = {
  status: string; graded_at?: string; stale?: boolean; raw_records?: number;
  cohort_records?: number; duplicates_excluded?: number; counts?: Record<string, number>; note?: string;
  unresolved_evidence?: { unique_outcomes: number; counts: Record<string, number>;
    truncated: boolean; items: { sport: string; game_id: string; player_id?: string | null;
      kind: string; market: string; reason: string; available_player_stats: string[];
      espn_event_id?: string | null; mlb_game_pk?: string | null }[]; note: string };
  reports: { sport: string; kind: string; market: string; model_version: string;
    sample_size: number; independent_games: number; brier_score: number | null;
    paired_baseline_brier?: number | null; paired_baseline_samples?: number;
    log_loss: number | null; counts: Record<string, number> }[];
};

async function liveReports(): Promise<LiveReport> {
  try {
    const response = await fetch(`${apiUrl()}/calibration/live`, { headers: { Authorization: `Bearer ${process.env.FANTASY_API_TOKEN || ""}` }, cache: "no-store", signal: AbortSignal.timeout(20000) });
    return response.ok ? response.json() : { status: "unavailable", reports: [] };
  } catch { return { status: "unavailable", reports: [] }; }
}

async function calibrationReports(): Promise<{ reports: CalibrationReport[]; note?: string }> {
  try {
    const res = await fetch(`${apiUrl()}/calibration`, { headers: { Authorization: `Bearer ${process.env.FANTASY_API_TOKEN || ""}` }, cache: "no-store", signal: AbortSignal.timeout(20000) });
    if (!res.ok) throw new Error("Unavailable");
    return await res.json();
  } catch {
    return { reports: [], note: "Calibration API unavailable. Results are incomplete; retry shortly." };
  }
}

async function optionalReport(path: string) {
  try {
    const response = await fetch(`${apiUrl()}${path}`, {
      cache: "no-store", signal: AbortSignal.timeout(20000),
      headers: { Authorization: `Bearer ${process.env.FANTASY_API_TOKEN || ""}` },
    });
    return response.ok ? await response.json() : null;
  } catch { return null; }
}

function timeAgo(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)}h ago`;
  return `${Math.round(minutes / (60 * 24))}d ago`;
}

// Same 0.25 coin-flip reference scripts/run_calibration.py uses - shown here
// so a reader doesn't have to already know what a Brier score of 0.24 means.
const COIN_FLIP_BRIER = 0.25;

function BrierBar({ score }: { score: number | null }) {
  if (score === null) return null;
  // Clamp the visual scale to [0.15, 0.30] - real sports-model Briers cluster
  // tightly there, and the coin-flip reference (0.25) needs to sit visibly
  // left of center, not at the far edge.
  const clamped = Math.min(Math.max(score, 0.15), 0.3);
  const pct = ((0.3 - clamped) / (0.3 - 0.15)) * 100;
  const coinFlipPct = ((0.3 - COIN_FLIP_BRIER) / (0.3 - 0.15)) * 100;
  return (
    <div className="relative mt-2 h-1.5 w-full rounded-full bg-slate-800">
      <div
        className={`h-1.5 rounded-full ${score < COIN_FLIP_BRIER ? "bg-emerald-500" : "bg-red-500"}`}
        style={{ width: `${pct}%` }}
      />
      <div
        className="absolute top-0 h-1.5 w-px bg-slate-500"
        style={{ left: `${coinFlipPct}%` }}
        title="Coin-flip reference (0.25)"
      />
    </div>
  );
}

export default async function CalibrationPage() {
  const [{ reports, note }, live, odds, deployment, readinessResult, contextResult] = await Promise.all([
    calibrationReports(), liveReports(), optionalReport('/calibration/odds-status'),
    optionalReport('/calibration/deployment'), optionalReport('/calibration/prop-readiness'),
    optionalReport('/calibration/context-readiness'),
  ]);
  const readiness: PropReadiness | null = readinessResult;
  const context: ContextReadiness | null = contextResult;
  const sorted = [...reports].sort((a, b) => a.sport.localeCompare(b.sport) || a.market.localeCompare(b.market));

  return (
    <main className="mx-auto max-w-5xl p-4 sm:p-6 md:p-8">
      {(live.status === "unavailable" || !odds || !deployment || !readiness || !context) &&
        <p role="status" className="mb-4 text-amber-300">Some calibration data is unavailable. Missing results are not zero results; retry shortly.</p>}
      <PageHeader
        eyebrow="Recorded forecasts · measured outcomes"
        title="Calibration"
        description="Live results use probabilities saved before kickoff, not predictions reconstructed after the result. Lower Brier score and log loss are better. A 0.25 Brier score is the constant 50/50 reference, not proof of betting value."
      />

      <aside className="mb-6 rounded-lg border border-amber-700/50 bg-amber-950/20 p-4 text-sm text-amber-200">
        {deployment?.enabled
          ? "Experimental NCAAF moneyline calibration enabled by user override. Validation gates have NOT passed. Baseline probabilities are retained for comparison and rollback."
          : deployment ? "NCAAF moneyline calibration is disabled; the retained Elo baseline is serving." : "Deployment status unavailable."}
        {deployment?.distributions && <p className="mt-2">
          NCAAF spread override: {deployment.distributions.spread_enabled ? "enabled" : "disabled"}.
          Player-prop overrides: {deployment.distributions.player_prop_stats.join(", ") || "none"}.
          These candidates were tested on historical distributions, not actual-quote profitability.
          Totals, other sports, and unlisted props retain their existing models.
        </p>}
      </aside>
      <section className="mb-6 rounded-lg border border-slate-700 p-4 text-sm text-slate-300">
        <h2 className="font-semibold">Odds API collection</h2>
        <p>{odds ? `${odds.configured ? "Configured" : "Not configured"} · ${odds.quota_blocked ? "Paused by quota guard" : "Pacing active"} · Last reported credits: ${odds.telemetry?.remaining ?? "unknown"}` : "Status unavailable"}</p>
        {odds && <><p className="mt-2">{odds.sports.map((s: { sport: string; reason: string; interval_seconds: number }) => `${s.sport.toUpperCase()}: ${s.reason.replaceAll("_", " ")} (${s.interval_seconds / 3600}h interval)`).join(" · ")}</p>
          {odds.quota_blocked && <p>Guard retry in approximately {Math.ceil(odds.quota_retry_in_seconds / 3600)} hours.</p>}
          <p className="mt-2 text-xs text-slate-400">{odds.note}</p></>}
      </section>
      <details className="mb-6 rounded-lg border border-slate-700 bg-slate-900/40 p-4">
        <summary className="cursor-pointer font-semibold text-slate-100">Forecast context evidence</summary>
        <p className="my-3 text-xs text-slate-400">{context?.note || "Context-readiness data unavailable."}</p>
        {context?.latest_capture_at && <p className="mb-3 text-xs text-slate-400">Latest forecast capture: {timeAgo(context.latest_capture_at)} · {context.player_forecasts} player forecasts.</p>}
        {context && <div className="overflow-x-auto"><table className="w-full text-left text-sm text-slate-300">
          <thead className="text-xs uppercase text-slate-500"><tr>{["Input", "Status", "Captured evidence", "Safeguard"].map(label => <th key={label} className="p-2">{label}</th>)}</tr></thead>
          <tbody>{context.inputs.map(input => <tr key={input.name} className="border-t border-slate-800">
            <td className="p-2">{input.name}</td>
            <td className="p-2">{input.status.replaceAll("_", " ")}</td>
            <td className="p-2 font-mono text-xs">{input.forecast_records_with_evidence !== undefined ? `${input.forecast_records_with_evidence} forecasts · ${input.headline_references ?? 0} refs` : input.report_records === undefined ? "—" : `${input.report_records} reports`}</td>
            <td className="p-2 text-xs text-slate-400">{input.note}</td>
          </tr>)}</tbody>
        </table></div>}
      </details>
      <details className="mb-6 rounded-lg border border-slate-700 bg-slate-900/40 p-4">
        <summary className="cursor-pointer font-semibold text-slate-100">NCAAF prop coverage and blockers</summary>
        <p className="my-3 text-xs text-slate-400">{readiness?.note || "Readiness data unavailable."}</p>
        <p className="mb-3 text-xs text-slate-400">Historical backfill: up to 50 games hourly. Research: {readiness?.research_at ? timeAgo(readiness.research_at) : "awaiting first report"}.</p>
        {readiness && <div className="overflow-x-auto"><table className="w-full text-left text-sm text-slate-300">
          <thead className="text-xs uppercase text-slate-500"><tr>{["Prop", "Status", "Qualified / quotes", "History rows / games", "Reason"].map(t => <th className="p-2" key={t}>{t}</th>)}</tr></thead>
          <tbody>{readiness.families.map(row => <tr key={row.stat_type} className="border-t border-slate-800">
            <td className="p-2">{row.stat_type.replaceAll("_", " ")}</td>
            <td className="p-2">{row.status.replaceAll("_", " ")}</td>
            <td className="p-2 font-mono">{row.qualified_quotes} / {row.quotes}</td>
            <td className="p-2 font-mono">{row.historical_rows} / {row.historical_games}</td>
            <td className="p-2 text-xs text-slate-400">{row.reason}</td>
          </tr>)}</tbody>
        </table></div>}
      </details>
      <section className="mb-8 rounded-lg border border-slate-700 bg-slate-900/40 p-4">
        <h2 className="text-lg font-semibold text-slate-100">Live forecast performance</h2>
        <p className="mt-1 text-sm text-slate-400">
          {live.graded_at ? `Graded ${timeAgo(live.graded_at)} · updates every 30 minutes` : `Status: ${live.status.replaceAll("_", " ")}`}
          {live.stale && <span className="text-amber-300"> · Stale report — grading needs attention</span>}
        </p>
        <div className="my-4 flex flex-wrap gap-4 text-sm text-slate-300">
          <span>{live.cohort_records ?? 0} selected forecasts</span>
          <span>{live.counts?.graded ?? 0} graded</span>
          <span>{live.counts?.pending ?? 0} pending</span>
          <span>{live.counts?.push ?? 0} pushes</span>
          <span>{Object.entries(live.counts ?? {}).filter(([key]) => !["graded", "pending", "push"].includes(key)).reduce((sum, [, n]) => sum+n, 0)} missing / review / invalid</span>
          <span>{live.duplicates_excluded ?? 0} repeated observations excluded</span>
        </div>
        <p className="mb-4 text-xs leading-relaxed text-slate-400">{live.note || "Waiting for the first grading report. No performance claim is available yet."}</p>
        {live.unresolved_evidence && live.unresolved_evidence.unique_outcomes > 0 && <details className="mb-4 rounded border border-amber-800/60 bg-amber-950/20 p-3 text-sm">
          <summary className="cursor-pointer font-medium text-amber-200">
            {live.unresolved_evidence.unique_outcomes} unique outcomes need verified result evidence
          </summary>
          <p className="mt-2 text-xs text-amber-100/70">{live.unresolved_evidence.note}</p>
          <p className="mt-2 text-xs text-amber-100/70">
            {Object.entries(live.unresolved_evidence.counts).map(([reason, count]) => `${count} ${reason.replaceAll("_", " ")}`).join(" · ")}
            {live.unresolved_evidence.truncated ? " · examples capped at 200" : ""}
          </p>
          <div className="mt-3 max-h-72 overflow-auto"><table className="w-full text-left text-xs text-slate-300">
            <thead className="sticky top-0 bg-slate-950 text-slate-500"><tr>{["Sport / event", "Market", "Evidence gap", "Observed player stats"].map(label => <th key={label} className="p-2">{label}</th>)}</tr></thead>
            <tbody>{live.unresolved_evidence.items.map((row, index) => <tr key={`${row.game_id}-${row.player_id}-${row.market}-${index}`} className="border-t border-slate-800">
              <td className="p-2 uppercase">{row.sport}<br/><span className="font-mono normal-case text-slate-500">{row.espn_event_id || row.mlb_game_pk || row.game_id.slice(0, 8)}</span></td>
              <td className="p-2">{row.market.replaceAll("_", " ")}</td>
              <td className="p-2">{row.reason.replaceAll("_", " ")}</td>
              <td className="p-2 text-slate-400">{row.available_player_stats.length ? row.available_player_stats.join(", ") : "none"}</td>
            </tr>)}</tbody>
          </table></div>
        </details>}
        {live.reports.length > 0 && <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-slate-500"><tr>
              {["Sport / market", "Model", "Graded / games", "Brier", "Log loss", "Coverage"].map(label => <th key={label} className="p-2">{label}</th>)}
            </tr></thead>
            <tbody>{live.reports.map(row => <tr key={`${row.sport}-${row.kind}-${row.market}-${row.model_version}`} className="border-t border-slate-800 text-slate-300">
              <td className="p-2"><span className="uppercase">{row.sport}</span> · {row.kind}<br/>{row.market.replaceAll("_", " ")}</td>
              <td className="p-2 font-mono" title={row.model_version}>{row.model_version.slice(0, 8)}<br/><span className="text-xs text-slate-500">recorded version</span></td>
              <td className="p-2 font-mono">{row.sample_size} / {row.independent_games}</td>
              <td className="p-2 font-mono">{row.brier_score?.toFixed(4) ?? "—"}
                {row.paired_baseline_samples ? <div className="text-xs text-slate-500">Baseline {row.paired_baseline_brier?.toFixed(4)} ({row.paired_baseline_samples} paired)</div> : null}
              </td>
              <td className="p-2 font-mono">{row.log_loss?.toFixed(4) ?? "—"}</td>
              <td className="p-2 text-xs">{Object.entries(row.counts).map(([key, n]) => `${n} ${key.replaceAll("_", " ")}`).join(" · ")}</td>
            </tr>)}</tbody>
          </table>
        </div>}
      </section>

      <h2 className="mb-2 text-lg font-semibold text-slate-100">Historical replay</h2>
      <p className="mb-4 text-sm text-slate-400">These older replay reports are separate from live grading. The legacy threshold (Brier below 0.23, at least 50 samples) does not approve model promotion.</p>

      {note && (
        <p className="rounded-lg border border-slate-700 bg-slate-900/40 p-4 text-sm text-slate-400">{note}</p>
      )}

      {sorted.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {sorted.map((report) => (
            <div
              key={`${report.sport}-${report.market}`}
              className="rounded-lg border border-slate-700 bg-slate-900/40 p-4"
            >
              <div className="mb-3 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <SportBadge sport={report.sport} />
                  <MarketBadge market={report.market} />
                </div>
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] font-medium uppercase ${
                    report.passed_gate ? "bg-emerald-500/15 text-emerald-300" : "bg-red-500/15 text-red-300"
                  }`}
                >
                  {report.passed_gate ? "Replay threshold met" : "Below threshold"}
                </span>
              </div>

              <div className="flex items-baseline justify-between">
                <span className="text-xs uppercase text-slate-500">Brier score</span>
                <span className="font-mono text-lg text-slate-100">
                  {report.brier_score !== null ? report.brier_score.toFixed(4) : "—"}
                </span>
              </div>
              <BrierBar score={report.brier_score} />

              <dl className="mt-4 space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <dt className="text-slate-500">Log loss</dt>
                  <dd className="font-mono text-slate-300">
                    {report.log_loss !== null ? report.log_loss.toFixed(4) : "—"}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">Sample size</dt>
                  <dd className="font-mono text-slate-300">{report.sample_size} games</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">Seasons</dt>
                  <dd className="font-mono text-slate-300">{report.seasons_used.join(", ")}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-500">Evaluated</dt>
                  <dd className="text-slate-400">{timeAgo(report.evaluated_at)}</dd>
                </div>
              </dl>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
