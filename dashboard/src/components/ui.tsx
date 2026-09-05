export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-border bg-surface p-4 ${className}`}>
      {children}
    </div>
  );
}

// Shared header shape for every data page (Board, Recommendations, Best
// Bets, Calibration) - one responsive scale (smaller on phones, where a
// 4xl headline eats the whole first screen) instead of each page picking
// its own padding/heading size ad hoc.
export function PageHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description?: string;
}) {
  return (
    <header className="mb-6 md:mb-8">
      <p className="text-xs font-bold uppercase tracking-[.15em] text-emerald-400 sm:text-sm sm:tracking-[.2em]">
        {eyebrow}
      </p>
      <h1 className="mt-2 text-2xl font-bold tracking-tight sm:text-3xl md:text-4xl">{title}</h1>
      {description && <p className="mt-2 max-w-2xl text-sm text-slate-400 md:text-base">{description}</p>}
    </header>
  );
}

const MARKET_STYLES: Record<string, string> = {
  moneyline: "bg-blue-500/15 text-blue-300",
  spread: "bg-purple-500/15 text-purple-300",
  total: "bg-amber-500/15 text-amber-300",
};

export function MarketBadge({ market }: { market: string }) {
  const style = MARKET_STYLES[market] ?? "bg-gray-500/15 text-gray-300";
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium uppercase ${style}`}>{market}</span>;
}

const SPORT_STYLES: Record<string, string> = {
  nfl: "bg-emerald-500/15 text-emerald-300",
  ncaaf: "bg-orange-500/15 text-orange-300",
  nba: "bg-red-500/15 text-red-300",
  mlb: "bg-sky-500/15 text-sky-300",
  nhl: "bg-indigo-500/15 text-indigo-300",
};

export function SportBadge({ sport }: { sport: string }) {
  const style = SPORT_STYLES[sport] ?? "bg-gray-500/15 text-gray-300";
  return <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase ${style}`}>{sport}</span>;
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
