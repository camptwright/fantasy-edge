import { PageHeader, SportBadge, MarketBadge } from "@/components/ui";

// Static generation happens during the image build, before the API and its
// database are available - same reasoning as the Board/Recommendations pages.
export const dynamic = "force-dynamic";

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

async function calibrationReports(): Promise<{ reports: CalibrationReport[]; note?: string }> {
  const res = await fetch(`${apiUrl()}/calibration`, { cache: "no-store" });
  return res.ok ? res.json() : { reports: [] };
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
  const { reports, note } = await calibrationReports();
  const sorted = [...reports].sort((a, b) => a.sport.localeCompare(b.sport) || a.market.localeCompare(b.market));

  return (
    <main className="mx-auto max-w-5xl p-4 sm:p-6 md:p-8">
      <PageHeader
        eyebrow="Walk-forward backtest · honest, not flattering"
        title="Calibration"
        description="How well the Elo/totals baseline actually predicts real outcomes, measured by replaying finished games chronologically with only pre-game information. A Brier score of 0.25 is what guessing 50/50 on every game scores - lower is better, and a market only clears the gate below 0.23 with at least 50 graded games."
      />

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
                  {report.passed_gate ? "Passed" : "Not calibrated"}
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
