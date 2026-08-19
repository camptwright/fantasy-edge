import type { MarketAssessment } from "@/lib/types";
import { EmptyState, StatusBadge } from "@/components/ui";

export function MarketTable({ items }: { items: MarketAssessment[] }) {
  if (!items.length) return <EmptyState message="No market observations meet the current coverage and freshness gates." />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[700px] text-left text-sm">
        <thead className="border-b border-border text-xs uppercase tracking-wide text-gray-500"><tr><th className="px-3 py-3 font-medium">Selection</th><th className="px-3 py-3 font-medium">Market</th><th className="px-3 py-3 font-medium">Fair price</th><th className="px-3 py-3 font-medium">Edge</th><th className="px-3 py-3 font-medium">Status</th><th className="px-3 py-3 font-medium">Observed</th></tr></thead>
        <tbody>{items.map((item) => <tr key={item.id} className="border-b border-border/60 last:border-0"><td className="px-3 py-3 font-medium text-gray-200">{item.selection}<span className="ml-2 text-xs text-gray-500">{item.sport.toUpperCase()}</span></td><td className="px-3 py-3 text-gray-400">{item.market}</td><td className="px-3 py-3 font-mono text-gray-300">{item.fair_price_american === null ? "—" : item.fair_price_american > 0 ? `+${item.fair_price_american}` : item.fair_price_american}</td><td className="px-3 py-3 font-mono text-accent">{item.edge_percent === null ? "—" : `${item.edge_percent.toFixed(1)}%`}</td><td className="px-3 py-3"><StatusBadge status={item.status} /></td><td className="px-3 py-3 text-xs text-gray-500">{new Date(item.assessed_at).toLocaleString()}</td></tr>)}</tbody>
      </table>
    </div>
  );
}
