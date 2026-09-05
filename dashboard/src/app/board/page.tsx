import { MarketBadge, PageHeader, formatPercent, formatPrice } from "@/components/ui";

type Signal = {
  id: string;
  sport: string;
  market: string;
  selection: string;
  bookmaker: string;
  price_american: number | null;
  model_probability: number;
  fair_probability: number | null;
  implied_probability: number | null;
  ev_percent: number;
  matchup: string;
  game_time: string | null;
  game_status: string;
};

type Ranking = { team_id: string; team_name: string; rating: number };

const SPORTS = ["nfl", "ncaaf", "nba", "mlb", "nhl"] as const;
// Unbounded rendering of every priced signal made this page ~1MB of HTML
// once it covered all five sports (found live: 624 rows) - fine on
// desktop, not on a phone. Capped at the highest-EV rows per sport, with
// an explicit "top N of M" note rather than silently truncating.
const MAX_SIGNALS_PER_SPORT = 40;

// Static generation happens during the image build, before the API and its
// database are available - same reasoning as the Fantasy page.
export const dynamic = "force-dynamic";

function apiUrl(): string {
  return process.env.FANTASY_API_URL || "http://api:8000";
}

async function signals(sport: string): Promise<Signal[]> {
  const res = await fetch(`${apiUrl()}/signals?sport=${sport}`, { cache: "no-store" });
  return res.ok ? res.json() : [];
}

async function rankings(sport: string): Promise<Ranking[]> {
  const res = await fetch(`${apiUrl()}/rankings/${sport}`, { cache: "no-store" });
  return res.ok ? res.json() : [];
}

export default async function BoardPage() {
  const results = await Promise.all(
    SPORTS.map(async (sport) => {
      const [allSignals, sportRankings] = await Promise.all([signals(sport), rankings(sport)]);
      const sorted = [...allSignals].sort((a, b) => b.ev_percent - a.ev_percent);
      return {
        sport,
        signals: sorted.slice(0, MAX_SIGNALS_PER_SPORT),
        totalSignals: allSignals.length,
        rankings: sportRankings,
      };
    }),
  );

  return (
    <main className="mx-auto max-w-6xl p-4 sm:p-6 md:p-8">
      <PageHeader
        eyebrow="Elo baseline · not calibrated, not a claim of accuracy"
        title="Board"
        description="Moneyline, spread, and total signals from a transparent team-rating and scoring-average model, plus current rankings, across every sport this app tracks."
      />

      {results.map(({ sport, signals: sportSignals, totalSignals, rankings: sportRankings }) => (
        <section key={sport} className="mb-10">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-xl font-semibold uppercase sm:text-2xl">{sport}</h2>
            {totalSignals > sportSignals.length && (
              <span className="text-xs text-slate-500">
                Top {sportSignals.length} of {totalSignals} by EV%
              </span>
            )}
          </div>
          <div className="grid gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              {sportSignals.length === 0 ? (
                <p className="rounded-lg border border-slate-700 p-6 text-sm text-slate-400">
                  No priced signals yet for {sport}.
                </p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-slate-700">
                  <table className="w-full min-w-[720px] text-left text-sm">
                    <thead className="border-b border-slate-700 text-xs uppercase text-slate-500">
                      <tr>
                        <th className="px-3 py-3">Matchup</th>
                        <th className="px-3 py-3">Market</th>
                        <th className="px-3 py-3">Selection</th>
                        <th className="px-3 py-3">Price</th>
                        <th className="px-3 py-3">Model</th>
                        <th className="px-3 py-3">Implied</th>
                        <th className="px-3 py-3">EV%</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sportSignals.map((signal) => (
                        <tr key={signal.id} className="border-b border-slate-800 last:border-0">
                          <td className="px-3 py-3 text-slate-300">{signal.matchup}</td>
                          <td className="px-3 py-3">
                            <MarketBadge market={signal.market} />
                          </td>
                          <td className="px-3 py-3 font-medium text-slate-100">{signal.selection}</td>
                          <td className="px-3 py-3 font-mono text-slate-300">{formatPrice(signal.price_american)}</td>
                          <td className="px-3 py-3 font-mono text-slate-300">
                            {formatPercent(signal.model_probability * 100)}
                          </td>
                          <td className="px-3 py-3 font-mono text-slate-300">
                            {formatPercent(signal.implied_probability !== null ? signal.implied_probability * 100 : null)}
                          </td>
                          <td className="px-3 py-3 font-mono text-emerald-400">{signal.ev_percent.toFixed(1)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div>
              <h3 className="mb-2 text-sm uppercase text-slate-500">Rankings</h3>
              {sportRankings.length === 0 ? (
                <p className="rounded-lg border border-slate-700 p-4 text-sm text-slate-400">No ratings yet.</p>
              ) : (
                <ol className="space-y-1 rounded-lg border border-slate-700 p-4 text-sm">
                  {sportRankings.slice(0, 15).map((team, index) => (
                    <li key={team.team_id} className="flex justify-between gap-3">
                      <span className="truncate text-slate-300">
                        {index + 1}. {team.team_name}
                      </span>
                      <span className="shrink-0 font-mono text-slate-500">{team.rating.toFixed(0)}</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>
        </section>
      ))}
    </main>
  );
}
