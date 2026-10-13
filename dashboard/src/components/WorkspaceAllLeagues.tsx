import { dailyReview, fantasyToolHref, pct, pts, workspaceHref, type League, type Overview } from "@/lib/workspace";

type Item = { league: League; overview: Overview | null };

/** FantasyPros-style multi-league view: every league's matchup and top action, then your players across leagues. */
export function WorkspaceAllLeagues({ items }: { items: Item[] }) {
  const ready = items.filter((i): i is { league: League; overview: Overview } => i.overview?.status === "snapshot_available");
  // Players are matched across platforms by name + position (ids differ between Sleeper and ESPN).
  const exposure = new Map<string, { name: string; position: string | null; team: string | null; leagues: { name: string; started: boolean; points: number | null }[] }>();
  for (const { league, overview } of ready) {
    const starters = new Set((overview.matchup.mine?.starters ?? []).flatMap(s => s.player_id ? [s.player_id] : []));
    for (const p of overview.roster_players) {
      const key = `${p.name.toLowerCase()}|${p.position}`;
      const row = exposure.get(key) ?? { name: p.name, position: p.position, team: p.team, leagues: [] };
      row.leagues.push({ name: league.name, started: starters.has(p.player_id), points: p.consensus_week_points ?? p.points });
      exposure.set(key, row);
    }
  }
  const shared = [...exposure.values()].filter(r => r.leagues.length > 1)
    .sort((a, b) => b.leagues.length - a.leagues.length || (b.leagues[0].points ?? 0) - (a.leagues[0].points ?? 0));
  return <div className="space-y-8">
    <ul className="grid gap-4 lg:grid-cols-3" aria-label="League summaries">{items.map(({ league, overview }) => {
      if (!overview || overview.status !== "snapshot_available") return <li key={league.league_id} className="rounded-2xl border border-amber-800/70 p-5">
        <h2 className="font-semibold">{league.name}</h2>
        <p className="mt-2 text-sm text-slate-400">Snapshot not ready{overview?.message ? `: ${overview.message}` : ""}. Not an empty league.</p>
      </li>;
      const { matchup, outcomes } = overview;
      const p = outcomes.status === "estimated_research" ? outcomes.win_probability : null;
      const action = dailyReview(overview).find(r => r.attention) ?? dailyReview(overview)[0];
      const add = overview.engine_waivers.rows.find(r => r.ros_gain != null);
      return <li key={league.league_id} className="flex flex-col rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="truncate font-semibold">{league.name}</h2>
          <span className="shrink-0 text-[10px] uppercase tracking-wider text-slate-500">{league.platform} · wk {overview.week ?? "?"}</span>
        </div>
        <p className="mt-3 flex items-baseline justify-between gap-2 text-sm">
          <span className="truncate text-emerald-300">{matchup.mine?.name ?? "Your team"}</span>
          <span className="shrink-0 tabular-nums text-lg font-semibold">{pts(matchup.mine?.recorded_points)} – {pts(matchup.opponent?.recorded_points)}</span>
          <span className="truncate text-right text-slate-300">{matchup.opponent?.name ?? "Opponent"}</span>
        </p>
        {p != null ? <div className="mt-2" aria-label={`Estimated ${pct(p)} to win`}>
          <div className="flex h-2 overflow-hidden rounded-full bg-slate-700"><div className="bg-emerald-400" style={{ width: `${p * 100}%` }} /></div>
          <p className="mt-1 text-xs text-slate-400">{pct(p)} to win · simulation research</p>
        </div> : <p className="mt-2 text-xs text-slate-500">Win probability withheld ({outcomes.reason.replaceAll("_", " ")}).</p>}
        {action && <a href={fantasyToolHref(action.tool, league.league_id)} className={`mt-4 rounded-lg border p-3 text-sm hover:border-emerald-500 ${action.attention ? "border-amber-700/70" : "border-slate-800"}`}>
          <span className="block font-medium">{action.title}</span><span className="mt-1 block text-xs text-slate-400 line-clamp-2">{action.detail}</span></a>}
        {add && <a href={fantasyToolHref("waivers", league.league_id)} className="mt-2 rounded-lg border border-slate-800 p-3 text-sm hover:border-emerald-500">
          <span className="text-xs text-slate-500">Best add</span> <span className="font-medium">{add.add.name}</span>
          <span className="text-slate-500"> for {add.compare?.name ?? "a bench player"}</span> <span className="tabular-nums text-emerald-300">+{add.ros_gain!.toFixed(1)}</span></a>}
        <a href={workspaceHref("today", league.league_id)} className="mt-auto pt-4 text-sm text-emerald-200 underline underline-offset-4">Open league</a>
      </li>;
    })}</ul>
    <section aria-label="Players across leagues">
      <h2 className="text-lg font-semibold">Your players across leagues</h2>
      <p className="mt-1 text-xs text-slate-500">Rostered in more than one league; points are this week’s consensus where available, else the provider projection.</p>
      {!shared.length ? <p className="mt-3 rounded-xl border border-slate-800 p-4 text-sm text-slate-400">No player is on more than one of your rosters.</p> :
      <div className="workspace-scrollbar mt-3 overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full min-w-[34rem] text-sm">
          <thead className="bg-slate-900/70 text-xs text-slate-400"><tr><th scope="col" className="px-3 py-2 text-left font-medium">Player</th><th scope="col" className="px-3 py-2 text-left font-medium">Leagues</th><th scope="col" className="px-3 py-2 text-right font-medium">Week pts</th></tr></thead>
          <tbody>{shared.map(r => <tr key={`${r.name}|${r.position}`} className="border-t border-slate-800/70">
            <td className="px-3 py-2">{r.name}<span className="block text-[11px] text-slate-500">{r.position} · {r.team ?? "FA"}</span></td>
            <td className="px-3 py-2"><ul className="flex flex-wrap gap-1">{r.leagues.map(l => <li key={l.name} className={`rounded-full px-2 py-0.5 text-[11px] ${l.started ? "bg-emerald-500/15 text-emerald-200" : "bg-slate-800 text-slate-400"}`}>{l.name} · {l.started ? "starting" : "bench"}</li>)}</ul></td>
            <td className="px-3 py-2 text-right tabular-nums">{pts(r.leagues[0].points)}</td>
          </tr>)}</tbody>
        </table>
      </div>}
    </section>
  </div>;
}
