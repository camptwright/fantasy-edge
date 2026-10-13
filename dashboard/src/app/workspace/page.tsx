import Link from "next/link";
import { SnapshotRetry, SnapshotWindow } from "@/components/SnapshotWindow";
import { WorkspaceMatchup } from "@/components/WorkspaceMatchup";
import { WorkspaceRoster } from "@/components/WorkspaceRoster";
import { WorkspaceResearchStatus } from "@/components/WorkspaceResearchStatus";
import { WorkspaceLineupReview } from "@/components/WorkspaceLineupReview";
import { WorkspaceDailyBrief } from "@/components/WorkspaceDailyBrief";
import { WorkspaceComparison } from "@/components/WorkspaceComparison";
import { WorkspaceTrade } from "@/components/WorkspaceTrade";
import { WorkspaceOutlook } from "@/components/WorkspaceOutlook";
import { WorkspaceEngineWaivers } from "@/components/WorkspaceEngineWaivers";
import { WorkspacePlayerProfile } from "@/components/WorkspacePlayerProfile";
import { WorkspaceStartSit } from "@/components/WorkspaceStartSit";
import { QuickActions, PositionStrength } from "@/components/WorkspaceHomeExtras";
import { WorkspaceMarkets } from "@/components/WorkspaceMarkets";
import { WorkspaceProps } from "@/components/WorkspaceProps";
import { WorkspaceAllLeagues } from "@/components/WorkspaceAllLeagues";
import { WorkspaceTradeIdeas } from "@/components/WorkspaceTradeIdeas";
import { WorkspacePositionLadder } from "@/components/WorkspacePositionLadder";
import { SeasonTiles, WorkspaceStandings } from "@/components/WorkspaceStandings";
import { WorkspaceAreTheyPlaying } from "@/components/WorkspaceAreTheyPlaying";
import { WorkspaceLeagueAnalyzer } from "@/components/WorkspaceLeagueAnalyzer";
import { WorkspaceRecap } from "@/components/WorkspaceRecap";
import type { Recap, StandingsView, TradeIdeas } from "@/lib/workspace-api.generated";
import { WorkspaceResearch } from "@/components/WorkspaceResearch";
import { WorkspaceSettings } from "@/components/WorkspaceSettings";
import { fantasyApi } from "@/lib/fantasy-api";
import { FANTASY_TOOLS, ageLabel, fantasyTool, fantasyToolHref, researchContext, fantasyHref, workspaceHref, workspaceView, type League, type Overview } from "@/lib/workspace";

export const dynamic = "force-dynamic";
const panels: Record<"props" | "markets" | "research" | "settings", [string, string, string][]> = {
  props: [],
  markets: [
    ["/best-bets", "Compare opportunities", "Qualified signals and their source prices. Empty results are not proof of a broken model."],
    ["/board", "Team markets", "Games, team ratings and market context."],
    ["/ledger", "Betting ledger", "Track decisions and outcomes. Proxy closing prices are not verified CLV."],
    ["/recommendations", "Market briefing", "Explanations alongside the underlying signals."],
  ],
  research: [
    ["/experimental", "Experiments", "Separately evaluated candidates; the serving model is unchanged."],
    ["/calibration", "Calibration evidence", "Prediction performance and coverage."],
    ["/fantasy/models", "Fantasy evidence", "Prospective observations, qualification gaps and model lineage."],
    ["/experimental/results", "Missing-result queue", "Games and players whose results still need repair before grading."],
  ],
  settings: [
    ["/providers", "Provider coverage and quotas", "Check source availability before reading missing projections."],
    ["/operations", "Operations", "Job failures, backlog and service performance."],
  ],
};
const TITLES = { today: "Today", props: "Player props", markets: "Markets", research: "Research lab", settings: "Settings & health" };

function Tool({ href, title, detail }: { href: string; title: string; detail: string }) {
  return <Link href={href} prefetch={false} className="group rounded-xl border border-slate-800 bg-slate-900/60 p-5 hover:border-emerald-500/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300">
    <h2 className="flex items-center justify-between font-semibold">{title} <span aria-hidden="true" className="text-slate-500 group-hover:text-emerald-300">→</span></h2>
    <p className="mt-2 text-sm leading-relaxed text-slate-400">{detail}</p>
  </Link>;
}

export default async function WorkspacePage({ searchParams }: { searchParams: Promise<{ view?: string; league?: string; tool?: string; player?: string; compare?: string; week?: string; sport?: string }> }) {
  const query = await searchParams;
  const view = workspaceView(query.view);
  const tool = fantasyTool(query.tool);
  // Market/research navigation has no league/model fetch fan-out.
  const fantasy = view === "today" || view === "fantasy";
  const leagueData = fantasy ? await fantasyApi<{ items: League[] }>("/api/v2/fantasy/leagues", 3000) : null;
  const leagues = leagueData?.items.filter(league => league.sport === "nfl") ?? [];
  // "All leagues" (Today only): every league's overview side by side.
  const all = view === "today" && query.league === "all" && leagues.length > 1;
  const allItems = all ? await Promise.all(leagues.map(async item => ({ league: item,
    overview: await fantasyApi<Overview>(`/api/v2/fantasy/leagues/${encodeURIComponent(item.league_id)}/overview`, 3000) }))) : [];
  // Never silently show another league when a requested league is missing.
  const requested = query.league === "all" ? undefined : query.league;
  const selected = all ? undefined : requested ? leagues.find(league => league.league_id === requested) : leagues[0];
  const overview = selected ? await fantasyApi<Overview>(`/api/v2/fantasy/leagues/${encodeURIComponent(selected.league_id)}/overview`, 3000) : null;
  const league = selected?.league_id ?? query.league;
  const wantsStandings = (view === "today" || (view === "fantasy" && (tool === "overview" || tool === "league"))) && !!selected && overview?.status === "snapshot_available";
  const standings = wantsStandings ? await fantasyApi<StandingsView>(`/api/v2/fantasy/leagues/${encodeURIComponent(selected!.league_id)}/standings`, 4000) : null;
  const recapWeek = /^\d{1,2}$/.test(query.week ?? "") ? `?week=${query.week}` : "";
  const recap = view === "fantasy" && tool === "recap" && selected && overview?.status === "snapshot_available"
    ? await fantasyApi<Recap>(`/api/v2/fantasy/leagues/${encodeURIComponent(selected.league_id)}/recap${recapWeek}`, 4000) : null;
  const ideas = view === "fantasy" && tool === "trade" && selected && overview?.status === "snapshot_available"
    ? await fantasyApi<TradeIdeas>(`/api/v2/fantasy/leagues/${encodeURIComponent(selected.league_id)}/trade-ideas`, 4000) : null;
  const ready = overview?.status === "snapshot_available";
  const title = all ? "All leagues" : view === "fantasy" ? (tool === "player" ? "Player" : FANTASY_TOOLS.find(item => item.id === tool)?.label) : TITLES[view];
  const href = (id: string) => view === "fantasy" ? fantasyToolHref(tool === "player" ? "team" : tool, id) : workspaceHref(view, id);
  return <main>
    <div className="mx-auto max-w-6xl px-4 py-6 md:px-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          {fantasy && selected && <p className="truncate text-xs font-medium uppercase tracking-wider text-slate-400">{selected.name}{overview?.week ? ` · Week ${overview.week}` : ""}</p>}
          <h1 className="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">{title}</h1>
        </div>
        {fantasy && <div className="flex flex-wrap gap-2 text-xs">
          {ready && <span className="rounded-full border border-slate-700 px-3 py-1 text-slate-300">Updated <time dateTime={overview.generated_at ?? undefined}>{ageLabel(overview.generated_at, Date.now())}</time></span>}
          <span className="rounded-full border border-amber-700/60 px-3 py-1 text-amber-200">Research only · nothing is submitted</span>
        </div>}
      </header>
      {fantasy ? <>
        {leagues.length > 1 && <nav aria-label="Select league" className="workspace-scrollbar mt-5 flex gap-2 overflow-x-auto">{view === "today" && <a href={workspaceHref("today", "all")} aria-current={all ? "page" : undefined}
          className={`flex min-h-10 shrink-0 items-center rounded-full border px-4 text-sm ${all ? "border-emerald-500 bg-emerald-500/10 text-emerald-200" : "border-slate-700 text-slate-300 hover:border-slate-500"}`}>All leagues</a>}{leagues.map(item => <a key={item.league_id} href={href(item.league_id)} aria-current={selected?.league_id === item.league_id ? "page" : undefined}
          className={`flex min-h-10 shrink-0 items-center gap-2 rounded-full border px-4 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300 ${selected?.league_id === item.league_id ? "border-emerald-500 bg-emerald-500/10 text-emerald-200" : "border-slate-700 text-slate-300 hover:border-slate-500"}`}>{item.name}<span className="text-[10px] uppercase text-slate-500">{item.platform}</span></a>)}</nav>}
        {view === "fantasy" && <nav aria-label="Fantasy tools" className="workspace-scrollbar mt-4 flex gap-1 overflow-x-auto border-b border-slate-800 lg:hidden">{FANTASY_TOOLS.map(item => <a key={item.id} href={fantasyToolHref(item.id, league)} aria-current={tool === item.id ? "page" : undefined} className={`min-h-11 shrink-0 border-b-2 px-3 py-3 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300 ${tool === item.id ? "border-emerald-400 text-emerald-300" : "border-transparent text-slate-400 hover:text-slate-100"}`}>{item.label}</a>)}</nav>}
        {all ? <div className="mt-6"><WorkspaceAllLeagues items={allItems} /></div> : !selected ? <section role="status" className="my-6 rounded-xl border border-amber-800 p-5">
          <h2 className="font-semibold">{leagueData === null ? "League service unavailable" : query.league ? "Requested league is unavailable" : "No NFL leagues synced"}</h2>
          <p className="mt-2 text-sm text-slate-300">{leagueData === null ? "This is a connection or service error, not an empty roster. Try again or check Operations." : "Choose an available NFL league or check league sync in Settings."}</p>
        </section> : !ready ? <section role="status" className="my-6 rounded-xl border border-slate-700 p-5">
          <h2 className="font-semibold">Snapshot not ready</h2>
          <p className="mt-2 text-sm text-slate-300">{overview?.message ?? "The overview service is unavailable. This is not an empty lineup; retry shortly or check Settings."}</p>
          <SnapshotRetry />
        </section> : <div className="mt-6">
          <SnapshotWindow expiresAt={overview.expires_at}>
            {view === 'fantasy' && (tool === 'waivers' || tool === 'players') && <WorkspaceResearchStatus research={overview.research} />}
            {(view === 'today' || tool === 'overview') && <><SeasonTiles standings={standings} /><WorkspaceMatchup overview={overview} /><WorkspaceAreTheyPlaying overview={overview} /><QuickActions overview={overview} /><WorkspaceDailyBrief overview={overview} /><PositionStrength overview={overview} /><WorkspaceOutlook overview={overview} /></>}
            {view === 'fantasy' && tool === 'recap' && <WorkspaceRecap recap={recap} league={overview.league_id} />}
            {view === 'fantasy' && tool === 'league' && <div className="space-y-8"><WorkspaceStandings standings={standings} /><WorkspaceLeagueAnalyzer overview={overview} /><PositionStrength overview={overview} /></div>}
            {view === 'fantasy' && tool === 'startsit' && <WorkspaceStartSit key={league} overview={overview} />}
            {view === 'fantasy' && tool === 'team' && <WorkspaceAreTheyPlaying overview={overview} />}
            {view === 'fantasy' && tool === 'team' && <WorkspaceRoster overview={overview} section="team" />}
            {view === 'fantasy' && tool === 'team' && <WorkspaceLineupReview overview={overview} />}
            {view === 'fantasy' && tool === 'waivers' && <WorkspaceEngineWaivers overview={overview} />}
            {view === 'fantasy' && tool === 'waivers' && <WorkspacePositionLadder key={league} overview={overview} />}
            {view === 'fantasy' && tool === 'waivers' && <WorkspaceRoster overview={overview} section="waivers" />}
            {view === 'fantasy' && tool === 'player' && <WorkspacePlayerProfile overview={overview} playerId={query.player} />}
            {view === 'fantasy' && tool === 'players' && <div className="mt-6"><WorkspaceComparison key={`${league}:${query.player}:${query.compare}`} players={overview.comparison_players} initialPlayer={query.player} initialCompare={query.compare} lineup={{available:overview.lineup_changes.status === 'available', current:overview.matchup.mine?.starters.flatMap(p=>p.player_id?[p.player_id]:[]) ?? [], candidate:overview.starters.flatMap(p=>p.player_id?[p.player_id]:[]), reason:overview.lineup_changes.reason}} /></div>}
            {view === 'fantasy' && tool === 'trade' && <div className="mt-6 space-y-6"><WorkspaceTradeIdeas ideas={ideas} league={overview.league_id} /><WorkspaceTrade key={league} overview={researchContext(overview)} /></div>}
          </SnapshotWindow>
        </div>}
      </> : <>
        <div className="mt-6">{view === "props" ? <WorkspaceProps sport={query.sport === "ncaaf" ? "ncaaf" : "nfl"} /> : view === "markets" ? <WorkspaceMarkets /> : view === "research" ? <WorkspaceResearch /> : <WorkspaceSettings />}</div>
        {!!panels[view].length && <><h2 className="mt-8 text-lg font-semibold">Full tools</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-2">{panels[view].map(([path, title, detail]) => <Tool key={path} href={path.startsWith("/fantasy") ? fantasyHref(path, league) : path} title={title} detail={detail} />)}</div></>}
      </>}
    </div>
  </main>;
}
