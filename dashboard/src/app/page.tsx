import Link from "next/link";

export default function HomePage() {
  return (
    <main className="mx-auto max-w-6xl p-5 md:p-10">
      <header className="mb-10 max-w-3xl">
        <p className="text-xs font-bold uppercase tracking-[.2em] text-emerald-300">Fantasy Edge · Dashboard</p>
        <h1 className="mt-2 text-4xl font-bold tracking-tight md:text-6xl">Your football decision hub.</h1>
        <p className="mt-4 text-slate-400">Move between league-specific roster decisions and the wider sports board without losing the context behind each recommendation.</p>
      </header>
      <div className="grid gap-4 sm:grid-cols-2">
        <Link
          href="/fantasy"
          className="rounded-xl border border-emerald-800 bg-gradient-to-br from-emerald-950/60 to-slate-900 p-6 transition-colors hover:border-emerald-400 sm:p-7"
        >
          <p className="text-xs font-bold uppercase tracking-wider text-emerald-300">Sleeper leagues</p>
          <h2 className="mt-2 text-xl font-semibold sm:text-2xl">Fantasy workspace</h2>
          <p className="mt-2 text-sm text-slate-400">
            Sleeper multi-league workspace: lineup, waiver, matchup, and draft analysis.
          </p>
        </Link>
        <Link
          href="/board"
          className="rounded-xl border border-slate-700 bg-slate-900 p-6 transition-colors hover:border-emerald-400 sm:p-7"
        >
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">5 sports</p>
          <h2 className="mt-2 text-xl font-semibold sm:text-2xl">Sports board</h2>
          <p className="mt-2 text-sm text-slate-400">
            Moneyline, spread, and total signals from a transparent Elo/totals baseline, plus team
            rankings, across NFL, NCAAF, NBA, MLB, and NHL.
          </p>
        </Link>
        <Link
          href="/best-bets"
          className="rounded-xl border border-slate-700 bg-slate-900 p-6 transition-colors hover:border-emerald-400 sm:p-7"
        >
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Live ranking</p>
          <h2 className="mt-2 text-xl font-semibold sm:text-2xl">Best bets</h2>
          <p className="mt-2 text-sm text-slate-400">
            Every priced signal and qualified prop across all five sports, ranked by edge - no
            narrative, just the numbers.
          </p>
        </Link>
        <Link
          href="/recommendations"
          className="rounded-xl border border-slate-700 bg-slate-900 p-6 transition-colors hover:border-emerald-400 sm:p-7"
        >
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Local LLM</p>
          <h2 className="mt-2 text-xl font-semibold sm:text-2xl">Recommendations</h2>
          <p className="mt-2 text-sm text-slate-400">
            A narrated market briefing over the same real signals and props, plus a parlay builder
            for the picks you choose.
          </p>
        </Link>
        <Link
          href="/calibration"
          className="rounded-xl border border-slate-700 bg-slate-900 p-6 transition-colors hover:border-emerald-400 sm:col-span-2 sm:p-7"
        >
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">Walk-forward backtest</p>
          <h2 className="mt-2 text-xl font-semibold sm:text-2xl">Calibration</h2>
          <p className="mt-2 text-sm text-slate-400">
            How well the baseline actually predicts real outcomes, measured honestly against
            finished games - not just claimed.
          </p>
        </Link>
      </div>
    </main>
  );
}
