import { playerProfileHref, pts, type Overview } from "@/lib/workspace";

type Plan = { starter_id: string; starter_name: string; slot: string; replacement_id: string;
  replacement_name: string; replacement_points: number; check_by: string; replacement_kickoff: string;
  risk_adjusted_points?: number | null };
type View = { status: string; plans: Plan[]; blockers: {player_id: string; reason: string}[] };
const when = (iso: string) => new Date(iso).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit", timeZone: "America/Chicago" });

export function WorkspaceLateSwap({ overview }: { overview: Overview }) {
  const data = (overview as Overview & {late_swap?: View}).late_swap;
  if (!data?.plans?.length && !data?.blockers?.length) return null;
  return <section aria-label="Late swap plans" className="rounded-2xl border border-amber-500/25 bg-amber-500/5 p-5">
    <h2 className="font-semibold">If a starter is inactive</h2>
    <ul className="mt-3 space-y-3 text-sm">{data.plans.map(plan => <li key={plan.starter_id}>
      <p>Check <a className="font-medium hover:underline" href={playerProfileHref(overview.league_id, plan.starter_id)}>{plan.starter_name}</a> before {when(plan.check_by)}. If ruled inactive, start <a className="text-amber-200 hover:underline" href={playerProfileHref(overview.league_id, plan.replacement_id)}>{plan.replacement_name}</a> in {plan.slot}.</p>
      <p className="mt-1 text-xs text-slate-400">Backup projection {pts(plan.replacement_points)} · kickoff {when(plan.replacement_kickoff)}{plan.risk_adjusted_points != null ? ` · conditional plan value ${pts(plan.risk_adjusted_points)} points` : ""}.</p>
    </li>)}</ul>
    {!!data.plans.length && <p className="mt-3 text-xs text-slate-500">Each plan covers one absence. A shared backup can fill only one slot. Recheck the backup’s status; make the change on your fantasy platform. Plan value combines the historical play rate and both projections, assuming no workload restriction.</p>}
    {!!data.blockers.length && <details className="mt-3 text-xs text-slate-500"><summary className="cursor-pointer">Starters without a replacement plan ({data.blockers.length})</summary>
      <ul className="mt-2 space-y-1">{data.blockers.map(row => <li key={row.player_id}>{overview.roster_players.find(p => p.player_id === row.player_id)?.name ?? row.player_id}: {row.reason.replaceAll("_", " ")}</li>)}</ul>
    </details>}
  </section>;
}
