import Link from "next/link";
import { createApiLoader } from "@/lib/resilient-api";
import { MarketBadge, PageHeader, SportBadge, formatPrice } from "@/components/ui";

// Very large edges are real numbers computed from real data, never
// fabricated - but a player-prop projection is a rolling mean over as few
// as 4 realized games (src/services/projections.py's
// MIN_GAMES_FOR_PROJECTION) with no awareness of role changes, injuries,
// or a book pricing a bigger role than the sample reflects. Only the
// moneyline market currently has a real walk-forward calibration report
// at all (see /calibration) - flagging that here rather than presenting
// every ranked row with equal implied confidence.
const EDGE_CAVEAT_THRESHOLD = 60;

// Static generation happens during the image build, before the API and its
// database are available - same reasoning as the Board/Recommendations pages.
export const dynamic = "force-dynamic";

const SPORTS = ["nfl", "ncaaf", "nba", "mlb", "nhl"] as const;
const TOP_N = 30;

type Signal = {
  id: string;
  sport: string;
  market: string;
  selection: string;
  price_american: number | null;
  matchup: string;
  ev_percent: number;
};

type Prop = {
  id: string;
  sport: string;
  player_name: string;
  injury_context?: { status?: string; game_availability?: {status?: string} };
  stat_type: string;
  line: number;
  over_price_american: number | null;
  under_price_american: number | null;
  edge_percent: number | null;
  under_edge_percent: number | null;
};

type Opportunity = {
  key: string;
  sport: string;
  market: string;
  label: string;
  detail: string;
  price: number | null;
  edgePercent: number;
};

function signalToOpportunity(s: Signal): Opportunity {
  return {
    key: `signal:${s.id}`,
    sport: s.sport,
    market: s.market,
    label: s.selection,
    detail: s.matchup,
    price: s.price_american,
    edgePercent: s.ev_percent,
  };
}

function propToOpportunities(p: Prop): Opportunity[] {
  const out: Opportunity[] = [];
  const status = p.injury_context?.game_availability?.status || p.injury_context?.status || "unknown";
  const labels: Record<string, string> = {not_provided: "No event injury feed", no_player_report: "No report (availability unconfirmed)",
    reported_questionable: "Questionable (ESPN)", coverage_not_supported: "Coverage unsupported",
    no_current_player_report: "No current report (availability unconfirmed)"};
  const availability = labels[status] || status.replaceAll("_", " ");
  if (p.edge_percent !== null && p.over_price_american !== null) {
    out.push({
      key: `prop:${p.id}:over`,
      sport: p.sport,
      market: p.stat_type,
      label: `${p.player_name} Over ${p.line}`,
      detail: `${p.stat_type.replaceAll("_", " ")} · Availability: ${availability}`,
      price: p.over_price_american,
      edgePercent: p.edge_percent,
    });
  }
  if (p.under_edge_percent !== null && p.under_price_american !== null) {
    out.push({
      key: `prop:${p.id}:under`,
      sport: p.sport,
      market: p.stat_type,
      label: `${p.player_name} Under ${p.line}`,
      detail: `${p.stat_type.replaceAll("_", " ")} · Availability: ${availability}`,
      price: p.under_price_american,
      edgePercent: p.under_edge_percent,
    });
  }
  return out;
}

type SportFilter = (typeof SPORTS)[number] | "all";

function isSportFilter(value: string | undefined): value is SportFilter {
  return value === "all" || (SPORTS as readonly string[]).includes(value ?? "");
}

export default async function BestBetsPage({
  searchParams,
}: {
  searchParams: Promise<{ sport?: string; kind?: string }>;
}) {
  const query = await searchParams;
  const filter: SportFilter = isSportFilter(query.sport) ? query.sport : "all";
  const kind = query.kind === "player" || query.kind === "team" ? query.kind : "both";
  const sportsToFetch = filter === "all" ? SPORTS : [filter];
  const { fetchJson, failures } = createApiLoader();

  const perSport = await Promise.all(
    sportsToFetch.map(async (sport) => {
      const [signals, props] = await Promise.all([
        kind === "player" ? Promise.resolve([] as Signal[]) : fetchJson<Signal[]>(`/signals?sport=${sport}`, []),
        kind === "team" ? Promise.resolve([] as Prop[]) : fetchJson<Prop[]>(`/props/live?sport=${sport}&limit=30`, []),
      ]);
      return { signals, props };
    }),
  );

  // Ranked within whatever's currently selected, not sliced from a
  // global top-30 then filtered - a one-sport view should show that
  // sport's own top 30, not however many of the global top 30 happened
  // to belong to it.
  const opportunities = perSport
    .flatMap(({ signals, props }) => [
      ...(kind === "player" ? [] : signals.filter((s) => s.price_american !== null).map(signalToOpportunity)),
      ...(kind === "team" ? [] : props.flatMap(propToOpportunities)),
    ])
    .sort((a, b) => b.edgePercent - a.edgePercent)
    .slice(0, TOP_N);

  return (
    <main className="mx-auto max-w-4xl p-4 sm:p-6 md:p-8">
      <PageHeader
        eyebrow="Live quantitative ranking · no LLM, nothing cached"
        title="Best Bets"
        description="Every priced signal and qualified player prop, ranked by edge against the market price. Computed fresh on every request from the same Elo/totals/projection baseline as the Board and Recommendations pages - no narrative, just the numbers, sorted."
      />

      <nav className="mb-6 flex gap-1 overflow-x-auto" aria-label="Filter by sport">
        {(["all", ...SPORTS] as const).map((option) => {
          const active = option === filter;
          return (
            <Link
              key={option}
              href={`/best-bets?sport=${option}&kind=${kind}`}
              className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium uppercase transition-colors ${
                active ? "bg-emerald-500/15 text-emerald-300" : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
              }`}
            >
              {option === "all" ? "All sports" : option}
            </Link>
          );
        })}
      </nav>

      <nav className="mb-6 flex gap-2" aria-label="Filter by bet type">
        {(["both", "player", "team"] as const).map(option => <Link
          key={option} href={`/best-bets?sport=${filter}&kind=${option}`}
          aria-current={kind === option ? "page" : undefined}
          className={`rounded-md px-3 py-1.5 text-sm font-medium ${kind === option ? "bg-emerald-500/15 text-emerald-300" : "text-slate-400 hover:bg-white/5"}`}>
          {option === "both" ? "Both" : option === "player" ? "Player props" : "Team props"}
        </Link>)}
      </nav>

      <p className="mb-6 rounded-lg border border-amber-800/60 bg-amber-950/20 p-4 text-xs text-amber-200/90 sm:text-sm">
        A big edge here is a real number, not a fabricated one - but only the moneyline market has
        a measured{" "}
        <Link href="/calibration" className="underline hover:text-amber-100">
          calibration report
        </Link>{" "}
        against real outcomes. Player-prop projections average all eligible prior history, requiring at least 4
        realized games. Availability evidence is labeled and selected risk cases are held out, but injuries and role changes do not numerically adjust projections. Treat very large edges as
        a sign the model and the book disagree sharply, not as a guaranteed win.
      </p>

      {failures.length > 0 && (
        <p role="alert" className="mb-6 rounded-lg border border-amber-700 p-4 text-sm text-amber-200">
          Some live data is temporarily unavailable. Rankings may be incomplete; unavailable feeds are not shown. Refresh to retry.
          <span className="mt-2 block text-xs">Affected feeds: {failures.slice().sort().join(", ")}</span>
        </p>
      )}
      {opportunities.length === 0 ? (
        <p className="rounded-lg border border-slate-700 p-6 text-sm text-slate-400">
          {failures.length > 0 ? "Unable to load enough live data to show bets. This does not mean no bets qualify. Please refresh shortly." : filter === "all"
            ? "Nothing qualifies yet - check back once more games and props have real prices attached."
            : `Nothing qualifies for ${filter.toUpperCase()} yet - check back once more games and props have real prices attached.`}
        </p>
      ) : (
        <ol className="space-y-2">
          {opportunities.map((opp, index) => (
            <li
              key={opp.key}
              className="flex items-center gap-3 rounded-lg border border-slate-700 bg-slate-900/40 p-3 sm:gap-4 sm:p-4"
            >
              <span className="w-5 shrink-0 text-center font-mono text-sm text-slate-600">{index + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex flex-wrap items-center gap-1.5">
                  <SportBadge sport={opp.sport} />
                  <MarketBadge market={opp.market} />
                </div>
                <p className="truncate text-sm font-medium text-slate-100 sm:text-base">{opp.label}</p>
                <p className="truncate text-xs text-slate-500">{opp.detail}</p>
              </div>
              <div className="shrink-0 text-right">
                <p className="font-mono text-sm text-slate-300">{formatPrice(opp.price)}</p>
                <p className="font-mono text-sm font-semibold text-emerald-400">
                  {opp.edgePercent > EDGE_CAVEAT_THRESHOLD && (
                    <span className="mr-1 text-amber-400" title="Large edge - model and book disagree sharply">
                      ⚠
                    </span>
                  )}
                  +{opp.edgePercent.toFixed(1)}%
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}

      <p className="mt-6 text-xs text-slate-600">
        Want to combine a few of these into a parlay? Build it on the{" "}
        <Link href="/recommendations" className="text-emerald-400 hover:underline">
          Recommendations
        </Link>{" "}
        page, where the same signals and props carry a parlay slip.
      </p>
    </main>
  );
}
