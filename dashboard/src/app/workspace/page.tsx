import Link from "next/link";
import { SnapshotWindow } from "@/components/SnapshotWindow";
import { WorkspaceMatchup } from "@/components/WorkspaceMatchup";
import { WorkspaceRoster } from "@/components/WorkspaceRoster";
import { WorkspaceKeeper } from "@/components/WorkspaceKeeper";
import { WorkspaceResearchStatus } from "@/components/WorkspaceResearchStatus";
import { WorkspaceLineupReview } from "@/components/WorkspaceLineupReview";
import { WorkspaceDailyBrief } from "@/components/WorkspaceDailyBrief";
import { WorkspaceComparison } from "@/components/WorkspaceComparison";
import { WorkspaceTrade } from "@/components/WorkspaceTrade";
import { fantasyApi } from "@/lib/fantasy-api";
import { FANTASY_TOOLS, fantasyTool, fantasyToolHref, researchContext, fantasyHref, workspaceHref, workspaceView, type League, type Overview } from "@/lib/workspace";

export const dynamic = "force-dynamic";
const panels = {
  markets: [
    ["/best-bets", "Compare opportunities", "Review qualified signals and their source prices. Empty results are not proof of a broken model."],
    ["/board", "Team markets", "Explore games, team ratings, and market context."],
    ["/ledger", "Your betting ledger", "Track decisions and outcomes. Proxy closing prices are not verified CLV."],
    ["/parlays", "Parlay research", "Explore combinations. Research estimates are not actionable betting instructions."],
    ["/recommendations", "Market briefing", "Read explanations alongside the underlying signals."],
  ],
  research: [
    ["/experimental", "Experiments", "Explore separately evaluated candidates without changing the serving model."],
    ["/calibration", "Calibration evidence", "Inspect prediction performance and coverage."],
    ["/fantasy/models", "Fantasy evidence", "Review prospective observations, qualification gaps, and model lineage."],
  ],
  settings: [
    ["/providers", "Provider coverage and quotas", "Inspect source availability before interpreting missing projections."],
    ["/operations", "Operations", "Review job failures, backlog, and service performance."],
  ],
};

function Tool({ href, title, detail }: { href: string; title: string; detail: string }) {
  return <Link href={href} prefetch={false} className="rounded-xl border border-slate-700 bg-slate-900 p-5 hover:border-emerald-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300">
    <h2 className="font-semibold text-emerald-200">{title} <span aria-hidden="true">→</span></h2>
    <p className="mt-2 text-sm leading-relaxed text-slate-300">{detail}</p>
  </Link>;
}

export default async function WorkspacePage({ searchParams }: { searchParams: Promise<{ view?: string; league?: string; tool?: string; player?: string; compare?: string }> }) {
  const query = await searchParams;
  const view = workspaceView(query.view);
  const tool = fantasyTool(query.tool);
  // Market/research navigation has no league/model fetch fan-out.
  const fantasy = view === "today" || view === "fantasy";
  const leagueData = fantasy ? await fantasyApi<{ items: League[] }>("/api/v2/fantasy/leagues", 3000) : null;
  const leagues = leagueData?.items.filter(league => league.sport === "nfl") ?? [];
  // Never silently show another league when a requested league is missing.
  const selected = query.league ? leagues.find(league => league.league_id === query.league) : leagues[0];
  const overview = selected ? await fantasyApi<Overview>(`/api/v2/fantasy/leagues/${encodeURIComponent(selected.league_id)}/overview`, 3000) : null;
  const league = selected?.league_id ?? query.league;
  return <main id="workspace-content" className="mx-auto max-w-7xl px-5 py-8 md:py-12">
    <p className="text-xs font-semibold uppercase tracking-widest text-emerald-300">Your personal playbook · Preview</p>
    <h1 className="mt-2 text-3xl font-semibold tracking-tight">{view === "today" ? "Today’s game plan" : view === "fantasy" ? FANTASY_TOOLS.find(item => item.id === tool)?.label : view === "markets" ? "Markets" : view === "research" ? "Research lab" : "Settings & health"}</h1>
    <p className="mt-2 text-sm text-slate-400">Saved evidence · Research only · No lineup changes or wagers are submitted</p>
    {fantasy ? <>
      {leagues.length > 0 && <nav aria-label="Select league" className="workspace-scrollbar my-6 flex gap-3 overflow-x-auto">{leagues.map(item => <a key={item.league_id} href={view === 'fantasy' ? fantasyToolHref(tool, item.league_id) : workspaceHref(view, item.league_id)} aria-current={selected?.league_id === item.league_id ? "page" : undefined} className={`shrink-0 rounded-lg border px-4 py-3 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300 ${selected?.league_id === item.league_id ? "border-emerald-400 text-emerald-200" : "border-slate-700 text-slate-300"}`}>{item.name}<span className="ml-2 text-xs text-slate-400">{item.platform}</span></a>)}</nav>}
      {view === 'fantasy' && <nav aria-label="Fantasy tools" className="workspace-scrollbar flex gap-1 overflow-x-auto border-b border-slate-700">{FANTASY_TOOLS.map(item => <a key={item.id} href={fantasyToolHref(item.id, league)} aria-current={tool === item.id ? 'page' : undefined} className={`min-h-11 shrink-0 border-b-2 px-4 py-3 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300 ${tool === item.id ? 'border-emerald-400 text-emerald-300' : 'border-transparent text-slate-400 hover:text-slate-100'}`}>{item.label}</a>)}</nav>}
      {(!overview || overview.status !== 'snapshot_available') && <a href={view === 'fantasy' ? fantasyToolHref(tool, league) : workspaceHref(view, league)} className="mt-4 inline-flex min-h-11 items-center rounded-lg border border-emerald-700 px-4 text-sm text-emerald-200">Check for an updated snapshot</a>}
      {!selected ? <section role="status" className="my-6 rounded-xl border border-amber-800 p-5">
        <h2 className="font-semibold">{leagueData === null ? "League service unavailable" : query.league ? "Requested league is unavailable" : "No NFL leagues synced"}</h2>
        <p className="mt-2 text-sm text-slate-300">{leagueData === null ? "This is a connection or service error, not an empty roster. Try again or check Operations." : "Choose an available NFL league or review the current app’s league configuration."}</p>
      </section> : <section className="my-6 rounded-xl border border-slate-700 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">{selected.name}{overview?.week ? ` · Week ${overview.week}` : ""}</h2>
        <p role="status" className="mt-2 text-sm text-slate-300">{overview?.message ?? "The overview service is unavailable or has not been deployed yet. This is not an empty lineup. The current app remains available."}</p>
        {overview?.generated_at && <p className="mt-2 text-xs text-slate-400">Snapshot: <time dateTime={overview.generated_at}>{overview.generated_at}</time> · Expires: {overview.expires_at}. Freshness is checked when this page is loaded; refresh before acting.</p>}
        {overview?.status === "snapshot_available" && <SnapshotWindow expiresAt={overview.expires_at}>
          {view === 'fantasy' && (tool === 'waivers' || tool === 'players') && <WorkspaceResearchStatus research={overview.research} />}
          {(view === 'today' || tool === 'overview') && <><WorkspaceDailyBrief overview={overview} /><WorkspaceMatchup overview={overview} /></>}
          {view === 'fantasy' && tool === 'team' && <WorkspaceLineupReview overview={overview} />}
          {view === 'fantasy' && tool === 'team' && <WorkspaceKeeper key={`${league}:${overview.generated_at}`} league={overview.league_id} players={overview.roster_players} />}
          {view === 'fantasy' && (tool === 'team' || tool === 'waivers') && <WorkspaceRoster overview={overview} section={tool} />}
          {view === 'fantasy' && tool === 'players' && <div className="mt-6"><WorkspaceComparison key={`${league}:${overview.generated_at}:${query.player}:${query.compare}`} players={overview.comparison_players} initialPlayer={query.player} initialCompare={query.compare} lineup={{available:overview.lineup_changes.status === 'available', current:overview.matchup.mine?.starters.flatMap(p=>p.player_id?[p.player_id]:[]) ?? [], candidate:overview.starters.flatMap(p=>p.player_id?[p.player_id]:[]), reason:overview.lineup_changes.reason}} /></div>}
          {view === 'fantasy' && tool === 'trade' && <div className="mt-6"><WorkspaceTrade key={league} overview={researchContext(overview)} /></div>}
        </SnapshotWindow>}
        {overview?.status === "snapshot_available" && <details className="mt-4 text-sm"><summary className="cursor-pointer text-emerald-200">Evidence and limitations</summary><ul className="mt-3 list-disc space-y-2 pl-5 text-slate-300">{overview.notes.map(note => <li key={note}>{note}</li>)}</ul><p className="mt-3 break-all text-xs text-slate-400">Model: {overview.model_version ?? "unknown"} · Recipe: {overview.recipe_version ?? "unknown"} · Scoring contract: {overview.scoring_contract_hash ?? "unknown"}</p></details>}
      </section>}
      <details className="mt-6"><summary className="min-h-11 cursor-pointer text-sm text-slate-400">Legacy tools & model evidence</summary><div className="grid gap-4 md:grid-cols-2">
        <Tool href={fantasyHref("/fantasy/matchup", league)} title="Review your matchup" detail="Compare starter contributions and inspect missing projection coverage." />
        <Tool href={fantasyHref("/fantasy", league)} title="Review lineup and waivers" detail="Inspect roster candidates, locked slots, and potential add/drop moves in the current tools." />
        <Tool href={fantasyHref("/fantasy/values", league)} title="Explore player values and trades" detail="Review league-aware values and their schedule and history limitations." />
        <Tool href={fantasyHref("/fantasy/models", league)} title="Check model evidence" detail="Keep estimates, prospective observations, and qualified probabilities separate." />
      </div></details>
    </> : <div className="mt-8 grid gap-4 md:grid-cols-2">{panels[view].map(([path, title, detail]) => <Tool key={path} href={path.startsWith("/fantasy") ? fantasyHref(path, league) : path} title={title} detail={detail} />)}</div>}
  </main>;
}
