import { RecommendationsView } from "@/components/RecommendationsView";
import { PageHeader } from "@/components/ui";

// Static generation happens during the image build, before the API and its
// database are available - same reasoning as the Fantasy/Board pages.
export const dynamic = "force-dynamic";

const SPORTS = ["nfl", "ncaaf", "nba", "mlb", "nhl"] as const;

function apiUrl(): string {
  return process.env.FANTASY_API_URL || "http://api:8000";
}

export type Signal = {
  id: string;
  sport: string;
  market: string;
  selection: string;
  bookmaker: string;
  price_american: number | null;
  model_probability: number;
  ev_percent: number;
  matchup: string;
  game_time: string | null;
  game_status: string;
};

export type Prop = {
  id: string;
  sport: string;
  player_name: string;
  team_name: string | null;
  stat_type: string;
  line: number;
  over_price_american: number | null;
  under_price_american: number | null;
  projection: number | null;
  edge_percent: number | null;
  model_probability: number | null;
  under_model_probability: number | null;
  under_edge_percent: number | null;
};

type Recommendation = { narrative: string | null; generated_at: string | null; note?: string };

async function fetchJson<T>(path: string, fallback: T): Promise<T> {
  const res = await fetch(`${apiUrl()}${path}`, { cache: "no-store" });
  return res.ok ? res.json() : fallback;
}

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.round(minutes / 60)}h ago`;
}

export default async function RecommendationsPage() {
  const [recommendation, bySport] = await Promise.all([
    fetchJson<Recommendation>("/recommendations", { narrative: null, generated_at: null }),
    Promise.all(
      SPORTS.map(async (sport) => {
        const [signals, props] = await Promise.all([
          fetchJson<Signal[]>(`/signals?sport=${sport}`, []),
          fetchJson<Prop[]>(`/props?sport=${sport}`, []),
        ]);
        // Filtered/limited here, server-side, before this ever reaches the
        // client component - /signals?sport=nfl alone can return ~2,000
        // rows and /props thousands more, and only the top 8 of each are
        // ever displayed. Passing the full arrays as client component
        // props would serialize all of them into the page's hydration
        // payload for no reason (found live: a 3.8MB page before this fix).
        const topSignals = signals
          .filter((s) => s.price_american !== null)
          .sort((a, b) => b.ev_percent - a.ev_percent)
          .slice(0, 8);
        const topProps = props
          .filter((p) => p.edge_percent !== null || p.under_edge_percent !== null)
          .sort(
            (a, b) =>
              Math.max(b.edge_percent ?? -Infinity, b.under_edge_percent ?? -Infinity) -
              Math.max(a.edge_percent ?? -Infinity, a.under_edge_percent ?? -Infinity),
          )
          .slice(0, 8);
        return { sport, signals: topSignals, props: topProps };
      }),
    ),
  ]);

  return (
    <main className="mx-auto max-w-6xl p-4 pb-24 sm:p-6 md:p-8 lg:pb-8">
      <PageHeader
        eyebrow="LLM narrative over a transparent baseline · not calibrated, not gambling advice"
        title="Recommendations"
        description="Top signals and player props across every sport, narrated by the local model on a 30-minute refresh, plus a parlay builder for combining the picks you choose."
      />

      <RecommendationsView
        narrative={recommendation.narrative}
        narrativeNote={recommendation.note ?? null}
        generatedAgo={timeAgo(recommendation.generated_at)}
        bySport={bySport}
      />
    </main>
  );
}
