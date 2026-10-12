import { dailyReview, fantasyToolHref, type Overview } from '@/lib/workspace';

export function WorkspaceDailyBrief({overview}: {overview: Overview}) {
  const rows = dailyReview(overview);
  if (!rows.length) return null;
  return <section className="mt-8" aria-label="Your daily review">
    <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
      <h2 className="text-lg font-semibold">Priorities</h2>
      <p className="text-xs text-slate-500">Evidence gaps first · review only, never automatic moves</p>
    </div>
    <ol className="divide-y divide-slate-800 overflow-hidden rounded-xl border border-slate-800">{rows.map((row, index) => <li key={row.title}>
      <a href={fantasyToolHref(row.tool, overview.league_id)}
        className="group flex items-start gap-4 p-4 hover:bg-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-emerald-300">
        <span aria-hidden="true" className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-bold ${row.attention ? 'bg-amber-400/15 text-amber-300' : 'bg-emerald-400/15 text-emerald-300'}`}>{index + 1}</span>
        <span className="min-w-0 flex-1">
          <span className="sr-only">{row.attention ? 'Check evidence: ' : 'Research: '}</span>
          <span className="block font-medium">{row.title}</span>
          <span className="mt-1 block text-sm leading-relaxed text-slate-400">{row.detail}</span>
        </span>
        <span aria-hidden="true" className="text-slate-600 group-hover:text-emerald-300">→</span>
      </a>
    </li>)}</ol>
  </section>;
}
