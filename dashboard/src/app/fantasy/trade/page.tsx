import Link from "next/link";
import { TradeCalculator } from "./TradeCalculator";

type League = { league_id: string; name: string; settings: Record<string, unknown> };
type Player = { player_id: string; name: string; position: string | null; team: string | null; projected_points: number; custom_projected_points: number | null };
type Roster = { roster_id: number; team_name: string; is_mine: boolean; players: Player[] };
type PackagePlayer = { player_id: string; name: string; position: string | null; trade_value: number };
type SuggestedTrade = {
  team_name: string;
  roster_id: number;
  you_give: PackagePlayer[];
  you_get: PackagePlayer[];
  give_total: number;
  get_total: number;
  fairness_pct: number;
  rationale: string;
};

function PackageList({ players }: { players: PackagePlayer[] }) {
  return <>{players.map((player, index) => <span key={player.player_id}>{index > 0 && " + "}<b>{player.name}</b> ({player.trade_value})</span>)}</>;
}
export const dynamic = "force-dynamic";

async function api<T>(path: string): Promise<T | null> {
  const token = process.env.FANTASY_API_TOKEN;
  if (!token) return null;
  const base = process.env.FANTASY_API_URL || "http://api:8000";
  const response = await fetch(`${base}${path}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  return response.ok ? response.json() : null;
}

function SuggestedTrades({ suggestions }: { suggestions: SuggestedTrade[] }) {
  if (!suggestions.length) {
    return <section className="rounded-xl border border-slate-800 bg-slate-900 p-5"><h2 className="font-semibold">Suggested trades</h2><p className="mt-2 text-sm text-slate-500">No realistic suggestions right now - either your roster has no clear positional surplus/need gap, or no other team&apos;s depth lines up with a fair-value package this week.</p></section>;
  }
  return (
    <section className="rounded-xl border border-emerald-800 bg-emerald-950/20 p-5">
      <h2 className="font-semibold text-emerald-200">Suggested trades</h2>
      <p className="mt-1 text-xs text-emerald-100/70">1-for-1 up to 2-for-2 packages using your roster depth to address a real positional gap, ranked by value fairness.</p>
      <div className="mt-3 space-y-3">
        {suggestions.map((trade, index) => (
          <div key={`${trade.roster_id}-${index}`} className="rounded-lg bg-black/20 p-4 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <b>{trade.team_name}</b>
              <span className="text-xs text-slate-400">Fairness: {trade.fairness_pct}%</span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-slate-300">
              <span>You give <PackageList players={trade.you_give} />{trade.you_give.length > 1 && ` = ${trade.give_total}`}</span>
              <span className="text-emerald-400">→</span>
              <span>You get <PackageList players={trade.you_get} />{trade.you_get.length > 1 && ` = ${trade.get_total}`}</span>
            </div>
            <p className="mt-2 text-xs text-slate-500">{trade.rationale}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export default async function TradePage({ searchParams }: { searchParams: Promise<{ league?: string }> }) {
  const query = await searchParams;
  const leagueData = await api<{ items: League[] }>("/api/v1/fantasy/leagues");
  const leagues = leagueData?.items ?? [];
  const selected = leagues.find((league) => league.league_id === query.league) ?? leagues[0];
  const [suggestionsData, rostersData] = selected ? await Promise.all([
    api<{ suggestions: SuggestedTrade[]; note: string }>(`/api/v1/fantasy/leagues/${selected.league_id}/trade/suggestions`),
    api<{ rosters: Roster[] }>(`/api/v1/fantasy/leagues/${selected.league_id}/trade/rosters`),
  ]) : [null, null];
  return <main className="mx-auto max-w-6xl overflow-x-hidden p-5 md:p-10">
    <header className="mb-8">
      <p className="text-xs font-bold uppercase tracking-[.2em] text-emerald-300">Fantasy Edge · Trade desk</p>
      <h1 className="mt-2 text-4xl font-bold tracking-tight md:text-6xl">Trade calculator.</h1>
      <p className="mt-3 max-w-2xl text-slate-400">Evaluate any proposed trade, or see suggested swaps that use your roster depth to fill a real positional gap.</p>
    </header>
    {!selected ? <p className="rounded-xl border border-slate-800 p-6 text-slate-400">No leagues synced yet.</p> : <>
      <nav className="-mx-5 mb-6 flex gap-3 overflow-x-auto px-5 md:mx-0 md:px-0">
        {leagues.map((league) => <Link key={league.league_id} href={`/fantasy/trade?league=${league.league_id}`} className={`min-w-56 shrink-0 rounded-xl border p-4 ${league.league_id === selected.league_id ? "border-emerald-500 bg-emerald-950/30" : "border-slate-800 bg-slate-900"}`}><b className="block truncate">{league.name}</b></Link>)}
      </nav>
      <div className="mb-6"><SuggestedTrades suggestions={suggestionsData?.suggestions ?? []} /></div>
      {rostersData ? <TradeCalculator leagueId={selected.league_id} rosters={rostersData.rosters} /> : <p className="rounded-xl border border-slate-800 p-6 text-slate-400">Roster data is not available yet.</p>}
    </>}
  </main>;
}
