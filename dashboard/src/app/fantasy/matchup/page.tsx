import Link from "next/link";

type League = { league_id: string; name: string; settings: Record<string, unknown> };
type Player = { player_id: string; name: string; position: string | null; team: string | null; projected_points: number; custom_projected_points: number | null };
type Side = { roster_id: number; starters: Player[]; bench?: Player[]; points: number; projected_points: number };
type Matchup = { week: number; your_roster: Side; opponent: Side | null };
export const dynamic = "force-dynamic";

async function api<T>(path: string): Promise<T | null> {
  const token = process.env.FANTASY_API_TOKEN;
  if (!token) return null;
  const base = process.env.FANTASY_API_URL || "http://api:8000";
  const response = await fetch(`${base}${path}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  return response.ok ? response.json() : null;
}

function Lineup({ title, side, bench = false }: { title: string; side: Side | null; bench?: boolean }) {
  const players = bench ? side?.bench ?? [] : side?.starters ?? [];
  return <section className="rounded-xl border border-slate-800 bg-slate-900"><header className="flex items-center justify-between gap-3 border-b border-slate-800 px-5 py-4"><h2 className="font-semibold">{title}</h2>{!bench && <span className="shrink-0 text-right"><span className="block font-mono text-emerald-300">{side?.points.toFixed(1) ?? "—"}</span><small className="block whitespace-nowrap text-slate-500">proj {side?.projected_points.toFixed(1) ?? "—"}</small></span>}</header>{players.length ? players.map((player) => <div key={player.player_id} className="flex items-center justify-between gap-3 border-b border-slate-800 px-5 py-3 last:border-0"><strong className="min-w-0 flex-1 truncate text-sm">{player.name}</strong><span className="flex shrink-0 items-center gap-3 text-xs text-slate-400"><span className="hidden whitespace-nowrap sm:inline">{[player.position, player.team].filter(Boolean).join(" · ")}</span><span className="text-right"><b className="block whitespace-nowrap font-mono text-emerald-300">{player.projected_points.toFixed(1)}</b><small className="block whitespace-nowrap text-slate-500">{player.custom_projected_points === null ? "model n/a" : `model ${player.custom_projected_points.toFixed(1)}`}</small></span></span></div>) : <p className="p-5 text-sm text-slate-500">No players available.</p>}</section>;
}

export default async function MatchupPage({ searchParams }: { searchParams: Promise<{ league?: string }> }) {
  const query = await searchParams;
  const leagueData = await api<{ items: League[] }>("/api/v1/fantasy/leagues");
  const leagues = leagueData?.items ?? [];
  const selected = leagues.find((league) => league.league_id === query.league) ?? leagues[0];
  const data = selected ? await api<Matchup>(`/api/v1/fantasy/leagues/${selected.league_id}/matchup`) : null;
  return <main className="mx-auto max-w-6xl overflow-x-hidden p-5 md:p-10"><header className="mb-8"><p className="text-xs font-bold uppercase tracking-[.2em] text-emerald-300">Sleeper · Week {data?.week ?? "—"}</p><h1 className="mt-2 text-4xl font-bold tracking-tight">Matchup center</h1><p className="mt-3 text-slate-400">Live lineup, official scoring, and Sleeper projections for the league you select. Actual scores read zero until games start; projections don&apos;t.</p></header>{leagues.length > 0 && <nav className="-mx-5 mb-6 flex gap-3 overflow-x-auto px-5 md:mx-0 md:px-0">{leagues.map((league) => <Link key={league.league_id} href={`/fantasy/matchup?league=${league.league_id}`} className={`min-w-52 shrink-0 rounded-xl border p-4 ${league.league_id === selected?.league_id ? "border-emerald-500 bg-emerald-950/30" : "border-slate-800 bg-slate-900"}`}><b className="block truncate">{league.name}</b><small className="text-slate-400">{String(league.settings.num_teams ?? "—")} teams</small></Link>)}</nav>}{!data ? <p className="rounded-xl border border-slate-800 p-6 text-slate-400">Matchup data is not available yet.</p> : <div className="grid grid-cols-1 gap-4 lg:grid-cols-2"><Lineup title="Your starters" side={data.your_roster} /><Lineup title="Opponent starters" side={data.opponent} /><div className="lg:col-span-2"><Lineup title="Your bench" side={data.your_roster} bench /></div></div>}</main>;
}
