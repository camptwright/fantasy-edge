import { playerProfileHref, pts } from "@/lib/workspace";
import type { TradeIdeas } from "@/lib/workspace-api.generated";

/** FantasyPros-style Trade Finder: one-for-one trades that help both starting lineups. Research only. */
export function WorkspaceTradeIdeas({ ideas, league }: { ideas: TradeIdeas | null; league: string }) {
  if (!ideas) return <p role="status" className="rounded-xl border border-amber-800 p-4 text-sm">Trade ideas unavailable. This is a service error, not a lack of trades.</p>;
  return <section aria-label="Trade ideas" className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
    <div className="flex flex-wrap items-end justify-between gap-2">
      <h2 className="text-lg font-semibold">Trade finder <span className="ml-1 rounded bg-sky-500/15 px-2 py-0.5 align-middle text-[11px] font-medium uppercase tracking-wider text-sky-300">Win–win research</span></h2>
      {ideas.status === "research" && <p className="text-xs text-slate-400">{ideas.mutual_trades} trades help both lineups · top {ideas.rows.length}</p>}
    </div>
    {ideas.status !== "research" || !ideas.rows.length ? <p className="mt-3 text-sm text-slate-400">{ideas.status === "research" ? "No one-for-one trade improves both starting lineups right now." : `Not available (${ideas.status.replaceAll("_", " ")}).`}</p> :
    <ol className="mt-4 space-y-2">{ideas.rows.map((r, i) => {
      const top = Math.max(r.my_gain, r.their_gain, 1);
      const gap = r.give_market_value != null && r.get_market_value != null ? r.get_market_value - r.give_market_value : null;
      return <li key={`${r.give.player_id}:${r.get.player_id}`} className="rounded-xl border border-slate-800 p-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <span className="text-xs tabular-nums text-slate-500">{i + 1}</span>
          <span>Give <a href={playerProfileHref(league, r.give.player_id)} className="font-semibold hover:underline">{r.give.name}</a> <span className="text-xs text-slate-500">{r.give.position}</span></span>
          <span aria-hidden="true" className="text-slate-600">⇄</span>
          <span>Get <a href={playerProfileHref(league, r.get.player_id)} className="font-semibold text-emerald-300 hover:underline">{r.get.name}</a> <span className="text-xs text-slate-500">{r.get.position}</span></span>
          <span className="text-xs text-slate-400">with {r.partner ?? "another team"}</span>
        </div>
        <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
          {([["Your lineup", r.my_gain, "bg-emerald-400"], [r.partner ?? "Their lineup", r.their_gain, "bg-sky-400"]] as const).map(([label, value, tone]) => <div key={label}>
            <dt className="flex justify-between text-slate-400"><span>{label}</span><span className="tabular-nums text-slate-200">+{value.toFixed(1)} pts</span></dt>
            <dd aria-hidden="true" className="mt-1 h-1.5 rounded bg-slate-800"><span className={`block h-1.5 rounded ${tone}`} style={{ width: `${(value / top) * 100}%` }} /></dd>
          </div>)}
        </dl>
        <p className="mt-2 text-[11px] text-slate-500">Over {r.weeks} remaining weeks · engine ROS {pts(r.give.engine_ros_points)} → {pts(r.get.engine_ros_points)}
          {gap != null ? ` · trade market ${Math.abs(gap) < Math.max(r.give_market_value ?? 0, r.get_market_value ?? 0) * 0.15 ? "values them about the same" : gap > 0 ? `values ${r.get.name} ${gap.toLocaleString()} higher (harder to get)` : `values ${r.give.name} ${(-gap).toLocaleString()} higher (you give more)`}` : ""}</p>
      </li>;
    })}</ol>}
    <p className="mt-3 text-xs text-slate-500">{ideas.note}</p>
  </section>;
}
