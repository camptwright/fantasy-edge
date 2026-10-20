"use client";
import { useMemo, useState } from "react";
import { american, bestSide, bookLabel, filterRows, percent, rate, sideRate, signedPct, sortRows, statLabel, type PropBoard as Board, type PropRow, type SortKey } from "@/lib/props";

const when = (iso: string) => new Date(iso).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit", timeZone: "America/Chicago" });
const evClass = (v: number | null) => v == null ? "text-slate-500" : v >= 0.02 ? "text-emerald-300" : v >= 0 ? "text-emerald-200/80" : "text-slate-400";
const rateClass = (v: number | null) => v == null ? "text-slate-500" : v >= 0.6 ? "text-emerald-300" : v <= 0.4 ? "text-rose-300" : "text-slate-300";

function Side({ row, side }: { row: PropRow; side: "over" | "under" }) {
  const best = side === "over" ? row.best_over : row.best_under;
  const ev = side === "over" ? row.ev_over : row.ev_under;
  const fair = row.fair_over == null ? null : side === "over" ? row.fair_over : 1 - row.fair_over;
  return <div className={`rounded-lg border px-2 py-1.5 ${ev != null && ev >= 0.02 ? "border-emerald-700/70 bg-emerald-500/5" : "border-slate-800"}`}>
    <p className="text-[11px] uppercase tracking-wider text-slate-500">{side === "over" ? "O" : "U"} {row.line}</p>
    <p className="tabular-nums">{best ? <>{american(best.price)} <span className="text-[11px] text-slate-500">{bookLabel(best.book)}</span></> : "—"}</p>
    <p className="text-[11px] tabular-nums"><span className="text-slate-500">fair {percent(fair)}</span> · <span className={evClass(ev)}>{signedPct(ev)}</span></p>
  </div>;
}

function Detail({ row }: { row: PropRow }) {
  return <div className="grid gap-3 border-t border-slate-800 p-3 text-xs md:grid-cols-[1fr_1fr]">
    <div>
      <p className="mb-1 font-semibold text-slate-300">Every book</p>
      <table className="w-full tabular-nums"><thead className="text-slate-500"><tr><th className="text-left font-normal">Book</th><th className="text-right font-normal">Line</th><th className="text-right font-normal">Over</th><th className="text-right font-normal">Under</th></tr></thead>
        <tbody>{row.offers.map(o => <tr key={`${o.book}:${o.line}`} className={o.line === row.line ? "" : "text-slate-500"}>
          <td>{bookLabel(o.book)}</td><td className="text-right">{o.line}</td><td className="text-right">{american(o.over)}</td><td className="text-right">{american(o.under)}</td></tr>)}</tbody></table>
      <p className="mt-1 text-slate-500">{row.books} book{row.books === 1 ? "" : "s"} in the no-vig consensus{row.hold != null ? ` · average hold ${percent(row.hold, 1)}` : ""}{row.spread != null ? ` · books disagree by ${percent(row.spread, 1)}` : ""}.</p>
    </div>
    <div>
      <p className="mb-1 font-semibold text-slate-300">Trend</p>
      <p className="text-slate-400">Last 5: <span className="tabular-nums text-slate-200">{row.hit.last5.join(" · ") || "—"}</span>{row.hit.average_l10 != null && <> · L10 avg <span className="tabular-nums text-slate-200">{row.hit.average_l10}</span></>}</p>
      <p className="mt-1 text-slate-400">Over hit rate: L5 {rate(row.hit.l5)} · L10 {rate(row.hit.l10)} · season {rate(row.hit.season)}{row.opponent ? ` · vs ${row.opponent} ${rate(row.hit.vs_opponent)}` : ""}</p>
      {row.dvp && <p className="mt-1 text-slate-400">{row.opponent} rank {row.dvp.rank} of {row.dvp.teams} allowing {statLabel(row.stat).toLowerCase()} to {row.position}s (1 = most).</p>}
      {row.engine && <p className="mt-1 text-slate-400">Engine projection {row.engine.projection}{row.engine.minutes != null ? ` in ${row.engine.minutes} min` : ""} · {percent(row.engine.over_probability)} over <span className="text-sky-300">(research)</span></p>}
    </div>
  </div>;
}

/** Line-shopping prop board: consensus fair price, best book per side, EV, hit rates, D vs Pos. */
export function PropBoard({ board }: { board: Board }) {
  const [stat, setStat] = useState("");
  const [book, setBook] = useState("");
  const [q, setQ] = useState("");
  const [valueOnly, setValueOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("ev");
  const [open, setOpen] = useState<string | null>(null);
  const [shown, setShown] = useState(40);
  const rows = useMemo(() => sortRows(filterRows(board.rows, { stat, book, q, minEv: valueOnly ? 0 : null }), sort), [board.rows, stat, book, q, valueOnly, sort]);
  const select = "min-h-10 rounded-lg border border-slate-700 bg-slate-950 px-2 text-sm";
  return <section aria-label="Prop board">
    <div className="flex flex-wrap items-end gap-2">
      <label className="min-w-0 flex-1 basis-40 text-xs text-slate-400">Search<input value={q} onChange={e => setQ(e.target.value)} placeholder="Player, team or game" className={`${select} mt-1 block w-full`} /></label>
      <label className="text-xs text-slate-400">Stat<select value={stat} onChange={e => setStat(e.target.value)} className={`${select} mt-1 block`}><option value="">All</option>{board.stats.map(s => <option key={s} value={s}>{statLabel(s)}</option>)}</select></label>
      <label className="text-xs text-slate-400">Book<select value={book} onChange={e => setBook(e.target.value)} className={`${select} mt-1 block`}><option value="">All</option>{board.books.map(b => <option key={b} value={b}>{bookLabel(b)}</option>)}</select></label>
      <label className="text-xs text-slate-400">Sort<select value={sort} onChange={e => setSort(e.target.value as SortKey)} className={`${select} mt-1 block`}>
        <option value="ev">Best EV</option><option value="l10">L10 hit rate</option><option value="dvp">Matchup (D vs Pos)</option><option value="time">Kickoff</option></select></label>
      <label className="flex min-h-10 items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={valueOnly} onChange={e => setValueOnly(e.target.checked)} className="h-4 w-4" />+EV only</label>
    </div>
    <p className="mt-2 text-xs text-slate-500">{rows.length} props · fair = no-vig average of every book at the main line · EV at the best price</p>
    {!rows.length ? <p role="status" className="mt-3 rounded-xl border border-slate-800 p-4 text-sm text-slate-400">{board.rows.length ? "No props match these filters." : board.sport === "nba" ? "No upcoming NBA props are posted yet. Books post them the day before tip-off; this board refreshes every 10 minutes." : "No upcoming props are posted yet. Books post most NFL props midweek; this board refreshes every 10 minutes."}</p> :
    <ul className="mt-3 space-y-2">{rows.slice(0, shown).map(r => {
      const side = bestSide(r);
      const l10 = sideRate(r.hit.l10, side);
      return <li key={r.key} className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/50">
        <button type="button" aria-expanded={open === r.key} onClick={() => setOpen(open === r.key ? null : r.key)}
          className="grid w-full grid-cols-[1fr_auto] items-center gap-3 p-3 text-left text-sm md:grid-cols-[minmax(10rem,1.4fr)_minmax(7rem,0.8fr)_repeat(2,minmax(7.5rem,1fr))_minmax(6rem,0.7fr)]">
          <span className="min-w-0"><span className="block truncate font-medium">{r.player}</span>
            <span className="block truncate text-[11px] text-slate-500">{r.position} · {r.team ?? "?"} vs {r.opponent ?? "?"} · {when(r.game_time)}</span></span>
          <span className="text-right md:text-left"><span className="block font-medium">{statLabel(r.stat)} {r.line}</span>
            <span className="block text-[11px] text-slate-500">{r.books} book{r.books === 1 ? "" : "s"}{r.other_lines.length ? ` · alt ${r.other_lines.join(", ")}` : ""}</span></span>
          <span className="col-span-2 grid grid-cols-2 gap-2 md:col-span-2"><Side row={r} side="over" /><Side row={r} side="under" /></span>
          <span className="col-span-2 flex items-center justify-between gap-2 text-[11px] md:col-span-1 md:block md:text-right">
            <span className={rateClass(l10)}>{side === "over" ? "Over" : "Under"} L10 {l10 == null ? "—" : `${Math.round(l10 * 100)}%`}</span>
            {r.dvp && <span className="block text-slate-500">D vs Pos {r.dvp.rank}/{r.dvp.teams}</span>}
          </span>
        </button>
        {open === r.key && <Detail row={r} />}
      </li>;
    })}</ul>}
    {rows.length > shown && <button type="button" onClick={() => setShown(shown + 40)} className="mt-3 min-h-11 w-full rounded-lg border border-slate-700 text-sm text-slate-300">Show more ({rows.length - shown} left)</button>}
  </section>;
}
