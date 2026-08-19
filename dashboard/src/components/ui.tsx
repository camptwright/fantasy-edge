export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-border bg-surface p-4 ${className}`}>
      {children}
    </div>
  );
}

const TIER_STYLES: Record<string, string> = {
  elite: "bg-yellow-500/15 text-yellow-400",
  strong: "bg-green-500/15 text-green-400",
  standard: "bg-blue-500/15 text-blue-400",
};

export function TierBadge({ tier }: { tier: string | null }) {
  if (!tier) return null;
  const style = TIER_STYLES[tier] ?? "bg-gray-500/15 text-gray-400";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium uppercase ${style}`}>
      {tier}
    </span>
  );
}

export function LoadingState() {
  return <p className="py-8 text-center text-sm text-gray-500">Loading…</p>;
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-red-900/50 bg-red-950/30 p-4 text-sm text-red-400">
      {message}
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return <p className="py-8 text-center text-sm text-gray-500">{message}</p>;
}

export function StatusBadge({ status }: { status: import("@/lib/types").MarketStatus }) {
  const labels: Record<import("@/lib/types").MarketStatus, string> = {
    qualified: "Qualified",
    stale: "Stale",
    coverage_incomplete: "Coverage incomplete",
    uncalibrated: "Uncalibrated",
    unsupported_market: "Unsupported",
    cannot_price_correlation: "Correlation unavailable",
  };
  const colors: Record<import("@/lib/types").MarketStatus, string> = {
    qualified: "bg-accent/15 text-accent",
    stale: "bg-amber-400/15 text-amber-300",
    coverage_incomplete: "bg-amber-400/15 text-amber-300",
    uncalibrated: "bg-purple-400/15 text-purple-300",
    unsupported_market: "bg-gray-400/15 text-gray-300",
    cannot_price_correlation: "bg-red-400/15 text-red-300",
  };
  return <span className={`rounded-full px-2 py-1 text-[11px] font-medium ${colors[status]}`}>{labels[status]}</span>;
}

export function formatPrice(price: number | null): string {
  if (price === null) return "—";
  return price > 0 ? `+${price}` : `${price}`;
}

export function formatPercent(value: number | null, digits = 1): string {
  if (value === null) return "—";
  return `${value.toFixed(digits)}%`;
}
