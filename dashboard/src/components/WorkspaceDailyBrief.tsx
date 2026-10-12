import { dailyReview, fantasyToolHref, type Overview } from '@/lib/workspace';

export function WorkspaceDailyBrief({overview}: {overview: Overview}) {
  const rows = dailyReview(overview);
  if (!rows.length) return null;
  return <section className="my-6" aria-label="Your daily review">
    <div className="mb-4 flex flex-wrap items-end justify-between gap-2">
      <h3 className="text-lg font-semibold">Your daily review</h3>
      <p className="text-xs text-slate-400">Evidence gaps first · review only, not automatic moves</p>
    </div>
    <div className="grid gap-3 md:grid-cols-2">{rows.map((row, index) => <a key={row.title}
      href={fantasyToolHref(row.tool, overview.league_id)}
      className="group rounded-xl border border-slate-700 bg-slate-950 p-4 transition-colors hover:border-emerald-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300">
      <div className="flex items-center justify-between gap-3"><span className={`text-xs font-semibold uppercase tracking-wider ${row.attention ? 'text-amber-200' : 'text-emerald-300'}`}>{row.attention ? 'Check evidence' : 'Research'} · {index+1}</span><span aria-hidden="true" className="text-slate-400 group-hover:text-emerald-300">↗</span></div>
      <h4 className="mt-3 font-semibold">{row.title}</h4>
      <p className="mt-2 text-sm leading-relaxed text-slate-400">{row.detail}</p>
    </a>)}</div>
  </section>;
}
