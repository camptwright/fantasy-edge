import { fantasyApi } from "@/lib/fantasy-api";
import { percent, signedPct, type PropBoard as Board } from "@/lib/props";
import { PropBoard } from "@/components/PropBoard";
import { ParlayGenerator } from "@/components/ParlayGenerator";

const SPORTS = [["nfl", "NFL"], ["ncaaf", "College"], ["nba", "NBA"]] as const;

/** Props workspace: line-shopping board, the value tracker's record, and the local-AI parlay generator. */
export async function WorkspaceProps({ sport }: { sport: "nfl" | "ncaaf" | "nba" }) {
  const board = await fantasyApi<Board>(`/props/board/${sport}?limit=500`, 6000);
  const t = board?.tracker;
  return <div className="space-y-6">
    <nav aria-label="Sport" className="flex gap-2">{SPORTS.map(([id, label]) => <a key={id} href={`/workspace?view=props&sport=${id}`} aria-current={sport === id ? "page" : undefined}
      className={`flex min-h-10 items-center rounded-full border px-4 text-sm ${sport === id ? "border-emerald-500 bg-emerald-500/10 text-emerald-200" : "border-slate-700 text-slate-300"}`}>{label}</a>)}</nav>
    {t && t.tracked > 0 && <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {([["Value picks tracked", String(t.tracked), "+3% EV with 3+ books, frozen when first seen"],
        ["Record", t.graded ? `${t.wins}-${t.graded - t.wins}` : "—", t.graded ? `${t.units > 0 ? "+" : ""}${t.units}u · ROI ${signedPct(t.roi)}` : "Awaiting results"],
        ["Beat the closing line", percent(t.beat_close), t.clv_n ? `${t.clv_n} picks with a close` : "Needs a pre-kickoff close"],
        ["Average CLV", signedPct(t.average_clv), "Close no-vig minus price taken"]] as const).map(([label, value, sub]) =>
        <div key={label} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4"><dt className="text-xs text-slate-400">{label}</dt><dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd><dd className="mt-1 text-[11px] text-slate-500">{sub}</dd></div>)}
    </dl>}
    <ParlayGenerator key={sport} sport={sport} books={board?.books ?? []} />
    {board === null ? <p role="status" className="rounded-xl border border-amber-800 p-4 text-sm">The props service is unavailable. This is a connection error, not an empty board.</p>
      : <PropBoard key={sport} board={board} />}
  </div>;
}
