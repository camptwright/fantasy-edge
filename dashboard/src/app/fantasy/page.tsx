import Link from "next/link";
import { AdviceButton } from "./AdviceButton";

type League = { league_id: string; name: string; status: string; settings: Record<string, unknown>; scoring_settings: Record<string, unknown> };
type NewsItem = { title: string; url: string; source: string };
type DropCandidate = { player_id: string; name: string; position: string | null; projected_points: number };
type Player = { player_id: string; name: string; position: string | null; team: string | null; opponent: string | null; projected_points: number; custom_projected_points: number | null; news?: NewsItem[]; recommended?: boolean; drop_candidate?: DropCandidate | null; suggested_faab_bid?: number | null };
type LineupSlot = { slot: string; player: Player | null };
type LineupSuggestion = { slot: string; sleeper_pick: { name: string; projected_points: number } | null; model_pick: { name: string; custom_projected_points: number } };
type Insight = { kind: string; title: string; detail: string };
type Draft = { score: number; covered_direct_slots: number; required_direct_slots: number; roster_size: number; position_source: string };
type Matchup = { week: number; your_roster: { points: number }; opponent: { points: number } | null };
export const dynamic = "force-dynamic";

async function api<T>(path: string): Promise<T | null> {
  const token = process.env.FANTASY_API_TOKEN;
  if (!token) return null;
  const response = await fetch(`${process.env.FANTASY_API_URL || "http://api:8000"}${path}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  return response.ok ? response.json() : null;
}

function NewsBlurb({ news }: { news?: NewsItem[] }) {
  if (!news || !news.length) return null;
  const item = news[0];
  return <a href={item.url} target="_blank" rel="noreferrer noopener" className="mt-1 block max-w-full truncate text-xs text-amber-300 hover:underline">📰 {item.title}</a>;
}

function WaiverMoveBlurb({ player }: { player: Player }) {
  if (!player.recommended || !player.drop_candidate) return null;
  return <p className="mt-1 truncate text-xs text-emerald-400">Drop <b>{player.drop_candidate.name}</b> ({player.drop_candidate.projected_points.toFixed(1)}){player.suggested_faab_bid ? ` · bid ~$${player.suggested_faab_bid}` : ""}</p>;
}

function ProjectionPair({ player }: { player: Player }) {
  return <span className="ml-3 shrink-0 text-right"><b className="block text-emerald-300">{player.projected_points.toFixed(1)}</b><small className="block whitespace-nowrap text-slate-500">{player.custom_projected_points === null ? "model n/a" : `model ${player.custom_projected_points.toFixed(1)}`}</small></span>;
}

function PlayerList({ title, players, sourcePending }: { title: string; players: Player[]; sourcePending: boolean }) {
  return <section className="rounded-xl border border-slate-800 bg-slate-900"><header className="flex items-center justify-between gap-3 border-b border-slate-800 px-5 py-4"><h2 className="font-semibold">{title}</h2><span className="shrink-0 text-xs text-slate-500">Sleeper / our model</span></header>{players.length ? players.map((player) => <div key={player.player_id} className={`flex items-center justify-between border-b border-slate-800 px-5 py-3 last:border-0 ${player.recommended ? "bg-emerald-950/20" : ""}`}><span className="min-w-0 flex-1"><b className="block truncate text-sm">{player.recommended && <span className="mr-1 text-amber-300" title="Projects to beat your worst current starter">★</span>}{player.name || player.player_id}</b><small className="block truncate text-slate-500">{[player.position, player.team, player.opponent && `vs ${player.opponent}`].filter(Boolean).join(" · ")}</small><WaiverMoveBlurb player={player} /><NewsBlurb news={player.news} /></span><ProjectionPair player={player} /></div>) : <p className="p-5 text-sm text-slate-500">{sourcePending ? "Sleeper has not published usable player-level projections through its public feed yet." : "No projection matches are available."}</p>}</section>;
}

function LineupSuggestions({ suggestions }: { suggestions: LineupSuggestion[] }) {
  if (!suggestions.length) return null;
  return <section className="mb-5 rounded-xl border border-amber-800/70 bg-amber-950/20 p-5">
    <h2 className="font-semibold text-amber-200">Where the two models disagree</h2>
    <p className="mt-1 text-xs text-amber-100/70">Sleeper&apos;s optimal lineup vs. our model&apos;s, slot by slot - agreement isn&apos;t shown, only where they&apos;d start someone different.</p>
    <div className="mt-3 space-y-2">
      {suggestions.map((s, i) => <div key={`${s.slot}-${i}`} className="flex flex-col gap-1 rounded-lg bg-black/20 px-4 py-2 text-sm sm:flex-row sm:items-center sm:gap-3">
        <b className="shrink-0 text-xs uppercase tracking-wider text-amber-300 sm:w-20">{s.slot.replaceAll("_", " ")}</b>
        <span className="min-w-0 flex-1 truncate text-slate-300">Sleeper: <b>{s.sleeper_pick?.name ?? "—"}</b> ({s.sleeper_pick?.projected_points.toFixed(1) ?? "—"})</span>
        <span className="min-w-0 flex-1 truncate text-slate-300">Our model: <b>{s.model_pick.name}</b> ({s.model_pick.custom_projected_points.toFixed(1)})</span>
      </div>)}
    </div>
  </section>;
}

function LineupList({ slots, sourcePending }: { slots: LineupSlot[]; sourcePending: boolean }) {
  return <section className="rounded-xl border border-emerald-800 bg-slate-900"><header className="flex items-center justify-between gap-3 border-b border-slate-800 px-5 py-4"><h2 className="font-semibold">Starting lineup</h2><span className="shrink-0 text-xs text-slate-500">Sleeper / our model</span></header>{slots.length ? slots.map((entry, index) => <div key={`${entry.slot}-${index}`} className="flex items-center justify-between border-b border-slate-800 px-5 py-3 last:border-0"><span className="flex min-w-0 flex-1 items-baseline gap-3"><b className="w-16 shrink-0 text-xs uppercase tracking-wider text-emerald-400">{entry.slot.replaceAll("_", " ")}</b>{entry.player ? <span className="min-w-0 flex-1"><b className="block truncate text-sm">{entry.player.name || entry.player.player_id}</b><small className="block truncate text-slate-500">{[entry.player.position, entry.player.team].filter(Boolean).join(" · ")}</small><NewsBlurb news={entry.player.news} /></span> : <span className="text-sm text-slate-600">No eligible player on roster</span>}</span>{entry.player && <ProjectionPair player={entry.player} />}</div>) : <p className="p-5 text-sm text-slate-500">{sourcePending ? "Sleeper has not published usable player-level projections through its public feed yet." : "Sync a roster to see a starting lineup."}</p>}</section>;
}

export default async function Fantasy({ searchParams }: { searchParams: Promise<{ league?: string }> }) {
  const query = await searchParams;
  const leagueData = await api<{ items: League[] }>("/api/v1/fantasy/leagues");
  const leagues = leagueData?.items ?? [];
  const selected = leagues.find((league) => league.league_id === query.league) ?? leagues[0];
  const [recs, analysis, draft, matchup] = selected ? await Promise.all([
    api<{ week: number; roster_positions: string[]; starting_lineup: LineupSlot[]; bench: Player[]; waivers: Player[]; lineup_suggestions: LineupSuggestion[]; notes: string[]; projection_status: "ready" | "source_pending"; projection_source: string }>(`/api/v1/fantasy/leagues/${selected.league_id}/recommendations`),
    api<{ insights: Insight[] }>(`/api/v1/fantasy/leagues/${selected.league_id}/analysis`),
    api<Draft>(`/api/v1/fantasy/leagues/${selected.league_id}/draft-score`),
    api<Matchup>(`/api/v1/fantasy/leagues/${selected.league_id}/matchup`),
  ]) : [null, null, null, null];
  const sourcePending = recs?.projection_status === "source_pending";
  return <main className="mx-auto max-w-7xl overflow-x-hidden p-5 md:p-10"><header className="mb-8"><p className="text-xs font-bold uppercase tracking-[.2em] text-emerald-300">Fantasy Edge · Sleeper intelligence</p><h1 className="mt-2 text-4xl font-bold tracking-tight md:text-6xl">Your weekly decision board.</h1><p className="mt-3 max-w-2xl text-slate-400">League rules, roster structure, live matchup state, and source-aware recommendations in one workspace.</p></header>{!selected ? <p className="rounded-xl border border-slate-800 p-6 text-slate-400">No leagues synced yet.</p> : <><nav className="-mx-5 mb-6 flex gap-3 overflow-x-auto px-5 md:mx-0 md:px-0">{leagues.map((league) => <Link key={league.league_id} href={`/fantasy?league=${league.league_id}`} className={`min-w-56 shrink-0 rounded-xl border p-4 ${league.league_id === selected.league_id ? "border-emerald-500 bg-emerald-950/30" : "border-slate-800 bg-slate-900"}`}><b className="block truncate">{league.name}</b><small className="capitalize text-slate-400">{league.status.replaceAll("_", " ")} · {String(league.settings.num_teams ?? "—")} teams</small></Link>)}</nav><section className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"><div className="rounded-xl border border-emerald-800 bg-emerald-950/30 p-5"><small className="uppercase text-slate-400">Format</small><b className="mt-1 block text-2xl">{String(selected.scoring_settings.rec ?? 0)}-PPR</b></div><div className="rounded-xl border border-slate-800 bg-slate-900 p-5"><small className="uppercase text-slate-400">Waiver budget</small><b className="mt-1 block text-2xl">${String(selected.settings.waiver_budget ?? "—")}</b></div><Link href={`/fantasy/matchup?league=${selected.league_id}`} className="rounded-xl border border-slate-800 bg-slate-900 p-5 transition hover:border-emerald-400"><small className="uppercase text-slate-400">Current matchup</small><b className="mt-1 block text-2xl">{matchup ? `${matchup.your_roster.points.toFixed(1)}${matchup.opponent ? ` – ${matchup.opponent.points.toFixed(1)}` : ""}` : "View"}</b></Link><div className="rounded-xl border border-slate-800 bg-slate-900 p-5"><small className="uppercase text-slate-400">Projection feed</small><b className="mt-1 block text-2xl">{recs?.projection_source ?? "Sleeper"}</b><small className="text-slate-500">{sourcePending ? "Awaiting usable records" : "Scored to league rules"}</small></div></section>{sourcePending && <p className="mb-4 rounded-xl border border-amber-800/70 bg-amber-950/30 p-4 text-sm text-amber-100">{recs?.projection_source ?? "Sleeper"} has not published usable player-level projection records for this week. Rankings resume automatically once the configured feed is populated.</p>}<LineupSuggestions suggestions={recs?.lineup_suggestions ?? []} /><section className="mb-5 grid grid-cols-1 gap-4 lg:grid-cols-2"><LineupList slots={recs?.starting_lineup ?? []} sourcePending={sourcePending}/><PlayerList title="Bench" players={recs?.bench ?? []} sourcePending={sourcePending}/></section><section className="mb-5"><PlayerList title="Waiver radar (★ beats your worst starter)" players={recs?.waivers ?? []} sourcePending={sourcePending}/></section><section className="mb-5"><AdviceButton leagueId={selected.league_id} /></section><section className="grid grid-cols-1 gap-4 lg:grid-cols-2"><div className="rounded-xl border border-slate-800 bg-slate-900 p-5"><h2 className="font-semibold">League-aware strategy</h2><div className="mt-4 space-y-4">{analysis?.insights.length ? analysis.insights.map((insight) => <div key={insight.kind}><b className="text-sm text-emerald-200">{insight.title}</b><p className="mt-1 text-sm text-slate-400">{insight.detail}</p></div>) : <p className="text-sm text-slate-500">League rules will appear after the next successful sync.</p>}</div></div><div className="rounded-xl border border-slate-800 bg-slate-900 p-5"><h2 className="font-semibold">Decision guardrails</h2><ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-slate-400">{recs?.notes.map((note) => <li key={note}>{note}</li>)}</ul>{draft && <p className="mt-4 border-t border-slate-800 pt-4 text-xs text-slate-500">Roster coverage uses {draft.position_source.toLowerCase()} and measures direct starting-position representation; it does not pretend to value players without a projection source.</p>}</div></section></>}</main>;
}
