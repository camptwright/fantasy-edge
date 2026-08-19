import { Card, StatusBadge } from "@/components/ui";
import type { MarketAssessment, SportsOverview } from "@/lib/types";

function AssessmentRow({ item }: { item: MarketAssessment }) {
  return (
    <div className="flex flex-col gap-2 border-b border-border/70 py-3 last:border-0 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="text-sm font-medium text-gray-200">{item.selection}</p>
        <p className="text-xs text-gray-500">{item.sport.toUpperCase()} · {item.market} · {item.league.toUpperCase()}</p>
      </div>
      <div className="flex items-center gap-3">
        {item.edge_percent !== null && <span className="font-mono text-sm text-accent">{item.edge_percent.toFixed(1)}% edge</span>}
        <StatusBadge status={item.status} />
      </div>
    </div>
  );
}

export function OverviewPanel({ overview }: { overview: SportsOverview }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[1.4fr_0.8fr]">
      <Card>
        <div className="mb-2 flex items-baseline justify-between gap-4">
          <div>
            <p className="eyebrow">Qualified board</p>
            <h2 className="mt-1 text-base font-semibold text-gray-100">What is worth a closer look</h2>
          </div>
          <span className="text-xs text-gray-500">{overview.qualified.length} items</span>
        </div>
        {overview.qualified.length ? overview.qualified.map((item) => <AssessmentRow key={item.id} item={item} />) : <p className="py-8 text-sm leading-6 text-gray-500">No qualified assessments yet. The board will stay quiet until coverage, freshness, and calibration gates pass.</p>}
      </Card>
      <Card>
        <p className="eyebrow">System readout</p>
        <h2 className="mt-1 text-base font-semibold text-gray-100">Model health</h2>
        <p className="mt-3 text-sm leading-6 text-gray-400">{overview.model_health?.status === "healthy" ? "All tracked feeds are operating within their configured gates." : "Model health is not available yet; no recommendations are being inferred."}</p>
        <div className="mt-5 flex items-center justify-between border-t border-border/70 pt-3 text-sm">
          <span className="text-gray-500">Version</span>
          <span className="font-mono text-gray-300">{overview.model_health?.model_version ?? "—"}</span>
        </div>
        <div className="mt-2 flex items-center justify-between text-sm">
          <span className="text-gray-500">Freshness</span>
          <span className="text-gray-300">{overview.freshness?.status ?? "Unavailable"}</span>
        </div>
      </Card>
    </div>
  );
}
