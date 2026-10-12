import { pts } from "@/lib/workspace";
import type { PlayerDetail, TradeOutlook, TradeOutlookSide } from "@/lib/workspace-api.generated";

const POSITIONS = ["QB", "RB", "WR", "TE"] as const;
const signed = (v: number | null | undefined) => v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(1)}`;
const tone = (v: number | null | undefined) => v == null || Math.abs(v) < 0.05 ? "text-slate-300" : v > 0 ? "text-emerald-300" : "text-rose-300";

/** WalterPicks-style trade value bars: each package's engine ROS points per player. */
function ValueBars({ label, ids, players, values, max, color }: { label: string; ids: string[]; players: PlayerDetail[]; values: Record<string, number | null>; max: number; color: string }) {
  const known = ids.every(id => values[id] != null);
  const total = ids.reduce((sum, id) => sum + (values[id] ?? 0), 0);
  return <div className="min-w-0">
    <p className="flex items-baseline justify-between text-xs text-slate-400"><span>{label} gives</span><span className="text-base font-semibold tabular-nums text-slate-100">{known ? total.toFixed(1) : "—"}</span></p>
    <ul className="mt-2 space-y-1.5">{ids.map(id => {
      const p = players.find(x => x.player_id === id), v = values[id];
      return <li key={id} className="text-xs">
        <span className="flex justify-between gap-2"><span className="truncate">{p?.name ?? id} <span className="text-slate-500">{p?.position}</span></span><span className="tabular-nums">{pts(v)}</span></span>
        <span aria-hidden="true" className="mt-0.5 block h-2 rounded bg-slate-800"><span className="block h-2 rounded" style={{ width: v == null ? "0%" : `${Math.max(2, (v / max) * 100)}%`, background: color }} /></span>
      </li>;
    })}</ul>
    {!known && <p className="mt-1 text-[11px] text-amber-200/80">A player has no engine research (K/DEF, unresolved, or stale), so no package total.</p>}
  </div>;
}

function SideTiles({ side }: { side: TradeOutlookSide }) {
  if (side.status !== "research") return <p className="text-sm text-slate-400">{side.team}: {side.status.replaceAll("_", " ")}. Missing is not zero.</p>;
  const max = Math.max(1, ...side.weekly.map(w => Math.abs(w.gain)));
  return <div className="min-w-0 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
    <div className="flex items-baseline justify-between gap-2">
      <h4 className="truncate font-semibold">{side.team}</h4>
      <p className="text-right"><span className={`text-2xl font-semibold tabular-nums ${tone(side.lineup_gain)}`}>{signed(side.lineup_gain)}</span><span className="block text-[11px] text-slate-500">lineup pts · {side.weeks} weeks</span></p>
    </div>
    <dl className="mt-3 grid grid-cols-4 gap-2">{POSITIONS.map(pos => {
      const v = side.by_position[pos];
      return <div key={pos} className={`rounded-lg border p-2 text-center ${v == null || Math.abs(v) < 0.05 ? "border-slate-800" : v > 0 ? "border-emerald-700/70 bg-emerald-500/10" : "border-rose-700/70 bg-rose-500/10"}`}>
        <dt className="text-[11px] font-medium text-slate-400">{pos}</dt><dd className={`text-sm font-semibold tabular-nums ${tone(v)}`}>{signed(v)}</dd>
      </div>;
    })}</dl>
    <ol aria-label={`${side.team} weekly lineup change`} className="relative mt-3 flex h-12 gap-1 border-y border-transparent before:absolute before:inset-x-0 before:top-1/2 before:border-t before:border-slate-700">{side.weekly.map(w => <li key={w.week} title={`Week ${w.week}: ${signed(w.gain)}`} className="relative h-full flex-1">
      <span aria-hidden="true" className={`absolute inset-x-0 mx-auto max-w-4 rounded-sm ${w.gain >= 0 ? "bottom-1/2 bg-emerald-400/80" : "top-1/2 bg-rose-400/80"}`} style={{ height: `${Math.max(4, (Math.abs(w.gain) / max) * 50)}%` }} />
      <span className="sr-only">Week {w.week} {signed(w.gain)}</span>
    </li>)}</ol>
    <p className="mt-1 flex justify-between text-[10px] text-slate-500"><span>W{side.weekly[0]?.week}</span><span>W{side.weekly.at(-1)?.week}</span></p>
    {!!side.unmodeled_players.length && <p className="mt-2 text-[11px] text-amber-200/80">Counted as zero (no engine research): {side.unmodeled_players.join(", ")}.</p>}
  </div>;
}

/** FantasyCalc trade-market index for each package: what the market pays, beside what the lineup gains. */
function MarketRow({ outlook, a, b }: { outlook: TradeOutlook; a: string; b: string }) {
  const m = outlook.market;
  if (!m) return null;
  if (m.status !== "observed") return <p className="mt-2 text-[11px] text-slate-500">Trade market value unavailable ({m.status.replaceAll("_", " ")}).</p>;
  const [ta, tb] = [m.side_a_total, m.side_b_total];
  const gap = ta != null && tb != null ? tb - ta : null;
  return <div className="mt-3 rounded-lg border border-slate-800 p-3 text-xs">
    <p className="flex flex-wrap justify-between gap-2"><span className="text-slate-400">Trade market value · FantasyCalc</span>
      <span className="tabular-nums">{a} gives {ta?.toLocaleString() ?? "—"} · {b} gives {tb?.toLocaleString() ?? "—"}</span></p>
    {gap != null && <p className="mt-1 text-slate-300">{Math.abs(gap) < Math.max(ta ?? 0, tb ?? 0) * 0.1 ? "The market values both packages about the same." : `The market favours ${gap > 0 ? a : b} receiving ${Math.abs(gap).toLocaleString()} more in value.`}</p>}
    <p className="mt-1 text-[11px] text-slate-500">{m.note}</p>
  </div>;
}

/** Engine-research trade outlook: value bars, per-position deltas and weekly lineup change for both sides. */
export function WorkspaceTradeOutlook({ outlook, a, b, players }: { outlook: TradeOutlook; a: string[]; b: string[]; players: PlayerDetail[] }) {
  if (outlook.status !== "research" || !outlook.side_a || !outlook.side_b) return <p role="status" className="rounded-xl border border-slate-800 p-4 text-sm text-slate-400">Rest-of-season outlook unavailable ({outlook.status.replaceAll("_", " ")}).</p>;
  const values = outlook.player_ros_points;
  const max = Math.max(1, ...Object.values(values).map(v => v ?? 0));
  const [sa, sb] = [outlook.side_a, outlook.side_b];
  const verdict = sa.lineup_gain != null && sb.lineup_gain != null
    ? Math.abs(sa.lineup_gain - sb.lineup_gain) < 5 ? "Roughly even for both starting lineups"
      : `${(sa.lineup_gain > sb.lineup_gain ? sa : sb).team} gains more starting-lineup points` : "One side has no engine outlook";
  return <section aria-label="Rest-of-season trade outlook" className="space-y-4">
    <div className="rounded-xl border border-slate-800 bg-gradient-to-br from-slate-900 to-slate-950 p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-sky-300">Rest-of-season outlook · engine research</p>
      <p className="mt-1 text-lg font-semibold">{verdict}</p>
      <div className="mt-4 grid gap-6 sm:grid-cols-2">
        <ValueBars label={sa.team ?? "Side A"} ids={a} players={players} values={values} max={max} color="#34d399" />
        <ValueBars label={sb.team ?? "Side B"} ids={b} players={players} values={values} max={max} color="#60a5fa" />
      </div>
      <p className="mt-3 text-[11px] text-slate-500">Bars are each player’s engine rest-of-season points (conditional on playing). Raw points ignore roster fit; the tiles below do not.</p>
      <MarketRow outlook={outlook} a={sa.team ?? "Side A"} b={sb.team ?? "Side B"} />
    </div>
    <div className="grid gap-4 md:grid-cols-2"><SideTiles side={sa} /><SideTiles side={sb} /></div>
    <p className="text-xs text-slate-500">{outlook.note}</p>
  </section>;
}
