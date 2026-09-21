import { PageHeader } from "@/components/ui";
import { NflPredictorLab, type LabData } from "@/components/NflPredictorLab";
import { createApiLoader } from "@/lib/resilient-api";
import { FootballPropResearch, type PropResearch } from "@/components/FootballPropResearch";
import { NflPlayerLab, type PlayerLabData } from "@/components/NflPlayerLab";
import { CollegePlayerLab, type CollegeLab } from "@/components/CollegePlayerLab";

export const dynamic = "force-dynamic";

export default async function NflPredictorPage({ searchParams }: { searchParams: Promise<{ league?: string }> }) {
  const { league } = await searchParams;
  const { fetchJson } = createApiLoader();
  const [data, props, players, college] = await Promise.all([
    fetchJson<LabData>("/experiments/nfl-predictor", { status: "unavailable", games: [] }),
    fetchJson<PropResearch>("/experiments/football-props", { status: "unavailable", seasons: [], metrics: [] }),
    fetchJson<PlayerLabData>(`/experiments/nfl-players${league ? `?league_id=${encodeURIComponent(league)}` : ""}`, { status: "unavailable", leagues: [], players: [] }),
    fetchJson<CollegeLab>("/experiments/college-players", {status:"unavailable",players:[],metrics:[]}),
  ]);
  return <main className="mx-auto max-w-6xl p-4 sm:p-6 md:p-8">
    <PageHeader eyebrow="Experimental · not used by Best Bets" title="NFL Predictor Lab"
      description="Explore the matchup. Inspect the evidence. Test the model against entire seasons—not one standout week." />
    <p className="mb-6 rounded-lg border border-amber-800/60 bg-amber-950/20 p-4 text-sm text-amber-200">Research preview. These probabilities are not promoted to the production model and do not change your Best Bets, bankroll sizing or calibration settings.</p>
    <NflPlayerLab data={players} />
    <a className="my-5 block rounded-lg border border-slate-700 p-4" href="/experimental/weather">Event venue and weather evidence →</a>
    <a className="my-5 block rounded-lg border border-amber-900 p-4" href="/experimental/results">Open shared missing-result queue →</a>
    <CollegePlayerLab data={college} />
    {data.status !== "experimental" && <p role="alert" className="mb-5 rounded-lg border border-slate-700 p-4 text-sm text-slate-300">The game predictor is temporarily unavailable or has not been trained. Refresh shortly; no predictions are fabricated.</p>}
    <NflPredictorLab data={data} />
    <FootballPropResearch data={props} />
  </main>;
}
