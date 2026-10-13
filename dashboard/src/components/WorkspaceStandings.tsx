import { pct } from "@/lib/workspace";
import type { StandingsView } from "@/lib/workspace-api.generated";

const ord = (n: number) => `${n}${["th", "st", "nd", "rd"][(n % 100 - 20) % 10] ?? ["th", "st", "nd", "rd"][n % 100] ?? "th"}`;

/** FantasyPros-style season tiles: standing, points per game, playoff odds. */
export function SeasonTiles({ standings }: { standings: StandingsView | null }) {
  if (!standings || standings.status !== "research") return null;
  const i = standings.rows.findIndex(r => r.is_mine);
  if (i < 0) return null;
  const me = standings.rows[i];
  const games = me.wins + me.losses + me.ties;
  const leagueAvg = standings.rows.reduce((a, r) => a + r.points_for / Math.max(1, r.wins + r.losses + r.ties), 0) / standings.rows.length;
  const ppg = me.points_for / Math.max(1, games);
  return <dl className="mb-4 grid grid-cols-3 gap-3" aria-label="Season">
    {([["Standing", ord(i + 1), `${me.wins}–${me.losses}${me.ties ? `–${me.ties}` : ""}`],
      ["Points per game", ppg.toFixed(1), `${ppg >= leagueAvg ? "+" : ""}${(ppg - leagueAvg).toFixed(1)} vs league`],
      ["Playoff odds", me.playoff_odds != null ? pct(me.playoff_odds) : "—", standings.playoff_teams ? `Top ${standings.playoff_teams} · simulated` : "simulated"]] as const)
      .map(([k, v, sub]) => <div key={k} className="rounded-xl border border-slate-800 bg-slate-900/60 p-3 sm:p-4">
        <dt className="text-[11px] text-slate-400 sm:text-xs">{k}</dt><dd className="mt-1 text-xl font-semibold tabular-nums sm:text-2xl">{v}</dd><dd className="text-[11px] text-slate-500">{sub}</dd></div>)}
  </dl>;
}

/** League standings with simulated playoff odds (League Analyzer-style). */
export function WorkspaceStandings({ standings }: { standings: StandingsView | null }) {
  if (!standings) return <p role="status" className="rounded-xl border border-amber-800 p-4 text-sm">Standings unavailable. This is a service error.</p>;
  if (standings.status !== "research") return <p role="status" className="rounded-xl border border-slate-800 p-4 text-sm text-slate-400">No standings yet ({standings.status.replaceAll("_", " ")}).</p>;
  return <section aria-label="Standings">
    <h2 className="text-lg font-semibold">Standings &amp; playoff odds</h2>
    <div className="workspace-scrollbar mt-3 overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full min-w-[40rem] text-sm">
        <thead className="bg-slate-900/70 text-xs text-slate-400"><tr>{["#", "Team", "Record", "PF", "PA", "Proj. wins", "Playoffs", "1st seed"].map((h, i) => <th key={h} scope="col" className={`px-3 py-2 font-medium ${i > 1 ? "text-right" : "text-left"}`}>{h}</th>)}</tr></thead>
        <tbody>{standings.rows.map((r, i) => <tr key={r.roster_id} className={`border-t border-slate-800/70 ${r.is_mine ? "bg-emerald-500/10" : ""} ${standings.playoff_teams && i === standings.playoff_teams - 1 ? "border-b-2 border-b-slate-600" : ""}`}>
          <td className="px-3 py-2 tabular-nums text-slate-500">{i + 1}</td>
          <td className="px-3 py-2">{r.name ?? r.roster_id}{r.is_mine && <span className="ml-2 text-[10px] uppercase tracking-wider text-emerald-300">You</span>}</td>
          <td className="px-3 py-2 text-right tabular-nums">{r.wins}–{r.losses}{r.ties ? `–${r.ties}` : ""}</td>
          <td className="px-3 py-2 text-right tabular-nums">{r.points_for.toFixed(1)}</td>
          <td className="px-3 py-2 text-right tabular-nums text-slate-400">{r.points_against.toFixed(1)}</td>
          <td className="px-3 py-2 text-right tabular-nums">{r.projected_wins?.toFixed(1) ?? "—"}</td>
          <td className="px-3 py-2 text-right"><span className="inline-flex items-center gap-2 tabular-nums">{r.playoff_odds != null ? pct(r.playoff_odds) : "—"}
            <span aria-hidden="true" className="h-1.5 w-12 rounded bg-slate-800"><span className="block h-1.5 rounded bg-emerald-400" style={{ width: `${(r.playoff_odds ?? 0) * 100}%` }} /></span></span></td>
          <td className="px-3 py-2 text-right tabular-nums text-slate-400">{r.first_seed_odds != null ? pct(r.first_seed_odds) : "—"}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <p className="mt-2 text-xs text-slate-500">{standings.remaining_games} games left · {standings.simulations.toLocaleString()} simulated seasons · line under the last playoff seed. {standings.note}</p>
  </section>;
}
