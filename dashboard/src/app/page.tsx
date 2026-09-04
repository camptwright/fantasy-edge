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
          className="rounded-xl border border-emerald-800 bg-gradient-to-br from-emerald-950/60 to-slate-900 p-7 transition-colors hover:border-emerald-400"
        >
          <p className="text-xs font-bold uppercase tracking-wider text-emerald-300">Sleeper leagues</p>
          <h2 className="mt-2 text-2xl font-semibold">Fantasy workspace</h2>
          <p className="mt-2 text-sm text-slate-400">
            Sleeper multi-league workspace: lineup, waiver, matchup, and draft analysis.
          </p>
        </Link>
        <Link
          href="/board"
          className="rounded-xl border border-slate-700 bg-slate-900 p-7 transition-colors hover:border-emerald-400"
        >
          <p className="text-xs font-bold uppercase tracking-wider text-slate-400">NFL & NCAAF</p>
          <h2 className="mt-2 text-2xl font-semibold">Sports board</h2>
          <p className="mt-2 text-sm text-slate-400">
            Moneyline and spread signals from a transparent Elo baseline, plus team rankings.
          </p>
        </Link>
      </div>
    </main>
  );
}
