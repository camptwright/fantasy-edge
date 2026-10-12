import {playerResearchHref, type Overview} from '@/lib/workspace';
import type {Starter} from '@/lib/workspace-api.generated';

export function WorkspaceLineupReview({overview}:{overview:Overview}) {
  const current=overview.matchup.mine?.starters ?? [];
  const candidate=overview.starters;
  const aligned=current.length===candidate.length && current.every((p,i)=>p.slot===candidate[i].slot);
  const currentIds=new Set(current.flatMap(p=>p.player_id ? [p.player_id] : []));
  function player(p:Starter | undefined) {
    if(!p) return <span className="text-slate-400">Slot correspondence unknown</span>;
    return <><p>{p.player_id ? <a className="text-emerald-200 underline underline-offset-4" href={playerResearchHref(overview.league_id,p.player_id)}>{p.name}</a> : p.name}</p><p className="mt-1 text-xs text-slate-400">{p.points==null?'Unknown points':`${p.points.toFixed(1)} pregame points`} · {p.source.replaceAll('_',' ')}{p.locked?' · Locked / game binding unknown':''}</p></>;
  }
  return <section aria-label="Lineup review" className="mt-6">
    <h3 className="text-lg font-semibold">Current lineup & candidate</h3>
    <p className="my-3 text-sm text-slate-300">{overview.lineup_changes.reason}</p>
    <p className="mb-3 text-xs text-slate-400">Review the whole lineup. FLEX reassignments are not independent swaps. These are saved pregame estimates, not remaining points or validated win probabilities. Confirm platform eligibility and availability before making changes.</p>
    {!candidate.length ? <p role="status">No candidate lineup is available. This does not mean your team has no starters.</p> : <div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="pb-3 text-left text-slate-400">Saved lineup status: {overview.lineup_status?.replaceAll('_',' ') ?? 'Unknown'}</caption><thead><tr>{['Slot','Current starter','Candidate starter','Review'].map(label=><th scope="col" key={label} className="p-3">{label}</th>)}</tr></thead><tbody>{candidate.map((p,i)=>{
      const old=aligned ? current[i] : undefined;
      const same=!!p.player_id && p.player_id===old?.player_id;
      const label=!p.player_id?'Unfilled / unresolved':same?'Same player':!aligned?'Current slot unknown':currentIds.has(p.player_id)?'Slot reassignment':'Candidate addition';
      return <tr key={`${p.slot}:${i}`} className="border-t border-slate-700"><th scope="row" className="p-3 font-medium">{p.slot}</th><td className="p-3">{player(old)}</td><td className="p-3">{player(p)}</td><td className="p-3"><p>{label}</p>{old?.player_id && p.player_id && !same && <a href={playerResearchHref(overview.league_id,old.player_id,p.player_id)} className="mt-2 inline-flex min-h-11 items-center text-emerald-200 underline">Compare evidence</a>}</td></tr>;
    })}</tbody></table></div>}
    {!aligned && !!current.length && <details className="mt-3"><summary className="min-h-11 cursor-pointer text-sm text-emerald-200">Current starters · slot layouts differ</summary><ul className="space-y-3">{current.map((p,i)=><li key={i} className="text-sm">{p.slot} · {player(p)}</li>)}</ul></details>}
  </section>;
}
