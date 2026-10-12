import type { FantasyResearch } from '@/lib/workspace-api.generated';

export function WorkspaceResearchStatus({ research }: { research?: FantasyResearch }) {
  if (!research) return null;
  return <section aria-label="Background fantasy experiments" className="my-5 rounded-lg border border-slate-700 p-4">
    <h3 className="font-semibold">Background model testing</h3>
    <p className="mt-2 text-sm text-slate-400">Separate research records, never automatic lineup or waiver advice. Missing outcomes remain missing; capture counts are not independent games or proof of accuracy.</p>
    <div className="mt-4 grid gap-4 md:grid-cols-2">{([['retention', 'Multiweek waiver retention'], ['specialists', 'Kicker, defense and rookie testing']] as const).map(([key, label]) => {
      const value = research[key];
      return <div key={key}><h4 className="text-sm font-medium">{label}</h4>
        <p className="mt-1 text-sm">{value.status.replaceAll('_', ' ')} · Not promoted</p>
        {value.generated_at && <p className="mt-1 text-xs text-slate-400">Last run: <time dateTime={value.generated_at}>{value.generated_at}</time></p>}
        {value.requested_weeks.length > 0 && <p className="mt-1 text-sm">Requested weeks: {value.requested_weeks.join(', ')}</p>}
        {value.status !== 'unavailable' && <p className="mt-1 text-sm">New captures in last run: {value.new_captures}</p>}
        {value.counts.length > 0 && <ul className="mt-2 text-sm text-slate-300">{value.counts.map(row => <li key={row.reason}>{row.reason.replaceAll('_', ' ')}: {row.count}</li>)}</ul>}
        {value.blockers.length > 0 && <details className="mt-2 text-sm"><summary className="cursor-pointer text-amber-200">Coverage blockers ({value.blockers.length})</summary><ul className="mt-2 text-slate-300">{value.blockers.map(row => <li key={row.reason}>{row.reason.replaceAll('_', ' ')}: {row.count}</li>)}</ul></details>}
      </div>;
    })}</div>
  </section>;
}
