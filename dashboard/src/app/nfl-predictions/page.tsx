"use client";

import useSWR from "swr";
import { Card, EmptyState, ErrorState, LoadingState, StatusBadge, formatPrice } from "@/components/ui";
import { fetcher } from "@/lib/api";

type TeamLine = { event_id: string; matchup: string; market: string; selection: string; line: number | null; price_american: number | null; source: string; model_probability: number | null; model_version: string | null; confidence: string | null; status: "qualified" | "uncalibrated" | "coverage_incomplete" };
type PlayerLine = { id: string; player_name: string; stat_type: string; line: number; over_price_american: number | null; under_price_american: number | null; source: string; model_projection: number | null; model_probability: number | null; status: "qualified" | "uncalibrated" | "coverage_incomplete" };
type Board = { status: string; team_lines: TeamLine[]; player_lines: PlayerLine[] };

function percent(value: number | null) { return value === null ? "—" : `${(value * 100).toFixed(1)}%`; }

export default function NFLPredictionsPage() {
  const { data, error, isLoading } = useSWR<Board>("/v1/nfl-predictions", () => fetcher<Board>("/v1/nfl-predictions"), { refreshInterval: 60_000 });
  return <div className="space-y-6">
    <header>
      <p className="eyebrow">NFL · model board</p>
      <h1 className="mt-2 text-2xl font-semibold text-gray-100">Predictions against the line</h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-400">ESPN game markets are shown alongside the calibrated NFL model. Player projections use the nflverse batch artifact only when the player and game join passes its sample and calibration gates.</p>
    </header>
    <Card className="border-accent/20 bg-accent/[0.04] text-sm text-gray-300"><span className="font-medium text-accent">Evidence rule.</span> A line without a qualified model probability stays visible for coverage tracking, but it is not a recommendation.</Card>
    {isLoading && <LoadingState />}{error && <ErrorState message={error.message} />}
    {data && <>
      <section className="space-y-3"><div><p className="eyebrow">ESPN game markets</p><h2 className="mt-1 text-lg font-medium text-gray-100">Team lines and model state</h2></div>
        <Card className="overflow-x-auto p-0"><table className="w-full min-w-[720px] text-left text-sm"><thead className="text-xs uppercase tracking-wide text-gray-500"><tr><th className="px-4 py-3">Matchup</th><th>Market</th><th>Selection</th><th>Line</th><th>Price</th><th>Model</th><th className="px-4">State</th></tr></thead><tbody>{data.team_lines.map((line, i) => <tr key={`${line.event_id}-${line.market}-${line.selection}-${i}`} className="border-t border-border/70"><td className="px-4 py-3 text-gray-300">{line.matchup}<span className="ml-2 text-xs uppercase text-gray-600">{line.source}</span></td><td className="py-3 text-gray-400">{line.market}</td><td className="py-3 text-gray-200">{line.selection}</td><td className="py-3 font-mono">{line.line ?? "—"}</td><td className="py-3 font-mono text-gray-400">{formatPrice(line.price_american)}</td><td className="py-3 text-gray-300">{percent(line.model_probability)}</td><td className="px-4 py-3"><StatusBadge status={line.status} /></td></tr>)}</tbody></table>{!data.team_lines.length && <EmptyState message="ESPN has not published NFL game lines in the current schedule window." />}</Card>
      </section>
      <section className="space-y-3"><div><p className="eyebrow">Player props</p><h2 className="mt-1 text-lg font-medium text-gray-100">nflverse projection coverage</h2></div>
        <Card className="overflow-x-auto p-0"><table className="w-full min-w-[680px] text-left text-sm"><thead className="text-xs uppercase tracking-wide text-gray-500"><tr><th className="px-4 py-3">Player</th><th>Prop</th><th>Line</th><th>Over / under</th><th>Projection</th><th>State</th></tr></thead><tbody>{data.player_lines.map((line) => <tr key={line.id} className="border-t border-border/70"><td className="px-4 py-3 text-gray-200">{line.player_name}<span className="ml-2 text-xs uppercase text-gray-600">{line.source}</span></td><td className="py-3 text-gray-400">{line.stat_type}</td><td className="py-3 font-mono">{line.line}</td><td className="py-3 font-mono text-gray-400">{formatPrice(line.over_price_american)} / {formatPrice(line.under_price_american)}</td><td className="py-3 text-gray-300">{line.model_projection ?? "—"}</td><td className="py-3"><StatusBadge status={line.status} /></td></tr>)}</tbody></table>{!data.player_lines.length && <EmptyState message="No NFL player lines are currently retained." />}</Card>
      </section>
    </>}
  </div>;
}
