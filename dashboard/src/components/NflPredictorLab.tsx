"use client";

import { useState } from "react";

type Metrics = { n: number; accuracy: number; brier: number; log_loss: number };
type TeamFeatures = { elo: number; sample: number; games: number; scored: number; allowed: number; margin: number; win_rate: number; rest: number; last_game: string | null };
type Game = {
  id: string; week: number | null; home: string; away: string; home_name: string; away_name: string;
  game_time: string | null; neutral: boolean; venue_verified: boolean; status: string;
  home_probability: number | null; away_probability?: number; baseline_home_probability?: number;
  home_features?: TeamFeatures; away_features?: TeamFeatures;
};
export type LabData = {
  status: string; version?: string; generated_at?: string; history_through?: string;
  history_games?: number; training_games?: number; new_results_applied?: number; games: Game[];
  evaluation?: { candidate: Metrics; elo: Metrics; home_prior: Metrics;
    seasons: { season: number; train_games: number; candidate: Metrics; elo: Metrics }[];
    reliability: { range: string; n: number; predicted: number; observed: number }[] };
};
const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
const when = (value: string | null) => value ? new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Chicago", weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
}).format(new Date(value)) : "Kickoff not confirmed";

export function NflPredictorLab({ data }: { data: LabData }) {
  const [selected, setSelected] = useState(data.games[0]?.id || "");
  const game = data.games.find(g => g.id === selected) || data.games[0];
  const evaluation = data.evaluation;
  const qualified = game?.home_probability != null && game.home_features && game.away_features;
  const comparisons: { label: string; key: keyof TeamFeatures; format: (n: number) => string }[] = [
    { label: "Replayed Elo", key: "elo", format: n => n.toFixed(0) },
    { label: "Points scored / game · last 8", key: "scored", format: n => n.toFixed(1) },
    { label: "Points allowed / game · last 8", key: "allowed", format: n => n.toFixed(1) },
    { label: "Point differential · last 8", key: "margin", format: n => `${n > 0 ? "+" : ""}${n.toFixed(1)}` },
    { label: "Win share · last 8 (ties = ½)", key: "win_rate", format: pct },
    { label: "Rest days · capped at 14", key: "rest", format: n => n.toFixed(0) },
  ];
  return <div className="space-y-8">
    <section className="grid gap-3 sm:grid-cols-3" aria-label="Experiment summary">
      {[
        ["Training examples", data.training_games?.toLocaleString() || "—", `History through ${data.history_through || "unknown"}`],
        ["Season-held-out accuracy", evaluation ? pct(evaluation.candidate.accuracy) : "—", "2022–2025 • never trained on the tested season"],
        ["Brier score · lower is better", evaluation ? evaluation.candidate.brier.toFixed(4) : "—", evaluation ? `Elo reference ${evaluation.elo.brier.toFixed(4)}` : "Evaluation unavailable"],
      ].map(([label,value,note]) => <div key={label} className="rounded-xl border border-slate-800 bg-slate-900/50 p-5">
        <p className="text-xs uppercase tracking-wider text-slate-400">{label}</p><p className="my-2 font-mono text-3xl text-slate-100">{value}</p><p className="text-xs text-slate-500">{note}</p>
      </div>)}
    </section>

    <section className="grid gap-5 lg:grid-cols-[280px_1fr]">
      <aside className="rounded-xl border border-slate-800 bg-slate-900/30 p-3">
        <h2 className="px-2 py-3 text-sm font-semibold">Upcoming slate <span className="ml-2 text-slate-500">{data.games.length}</span></h2>
        <p className="mb-3 px-2 text-xs text-slate-500">Next 14 days · times Central</p>
        <div className="max-h-[620px] space-y-2 overflow-y-auto">
          {data.games.map(g => <button key={g.id} onClick={() => setSelected(g.id)} aria-pressed={game?.id === g.id}
            className={`w-full rounded-lg border p-3 text-left transition-colors ${game?.id === g.id ? "border-emerald-500/60 bg-emerald-500/10" : "border-slate-800 hover:bg-slate-800/50"}`}>
            <span className="block text-xs text-slate-500">Week {g.week ?? "TBD"}</span>
            <span className="my-1 block font-semibold">{g.away} <span className="text-slate-500">@</span> {g.home}</span>
            <span className="block text-xs text-slate-400">{when(g.game_time)}</span>
          </button>)}
          {!data.games.length && <p className="p-3 text-sm text-slate-400">No upcoming NFL fixtures are available.</p>}
        </div>
      </aside>
      <article className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40">
        {!game ? <p className="p-8 text-slate-400">Select a matchup when the schedule is available.</p> : <>
          <div className="border-b border-slate-800 p-5 sm:p-7">
            <p className="text-xs uppercase tracking-widest text-emerald-400">Matchup explorer · week {game.week ?? "TBD"}</p>
            <h2 className="mt-3 text-xl font-semibold sm:text-2xl">{game.away_name} <span className="text-slate-500">at</span> {game.home_name}</h2>
            <p className="mt-2 text-sm text-slate-400">{when(game.game_time)} · {game.neutral ? "Neutral venue" : "Home venue"}{!game.venue_verified && " assumed — not verified"}</p>
          </div>
          {qualified ? <div className="space-y-6 p-5 sm:p-7">
            <div>
              <p className="mb-4 text-xs uppercase tracking-wider text-slate-500">Experimental win probability · conditional on no tie</p>
              <div className="flex justify-between gap-4">
                <div><p className="text-sm text-slate-400">{game.away}</p><p className="font-mono text-4xl text-sky-300">{pct(game.away_probability!)}</p></div>
                <div className="text-right"><p className="text-sm text-slate-400">{game.home}</p><p className="font-mono text-4xl text-emerald-300">{pct(game.home_probability!)}</p></div>
              </div>
              <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-slate-800" aria-label={`${game.away} ${pct(game.away_probability!)}; ${game.home} ${pct(game.home_probability!)}`}>
                <div className="bg-sky-400" style={{ width: pct(game.away_probability!) }} /><div className="bg-emerald-400" style={{ width: pct(game.home_probability!) }} />
              </div>
              <p className="mt-3 text-sm text-slate-400">Model lean: <span className="text-slate-100">{game.home_probability! >= .5 ? game.home_name : game.away_name}</span>. Elo reference: {game.home} {pct(game.baseline_home_probability!)}.</p>
            </div>
            <div className="overflow-x-auto"><table className="w-full text-sm">
              <caption className="mb-3 text-left text-xs uppercase tracking-wider text-slate-500">Pregame inputs · comparison, not causal attribution</caption>
              <thead><tr className="text-slate-400"><th className="py-2 text-left font-normal">Feature</th><th className="text-right font-normal">{game.away}</th><th className="text-right font-normal">{game.home}</th></tr></thead>
              <tbody>{comparisons.map(c => <tr key={c.key} className="border-t border-slate-800"><td className="py-3 text-slate-400">{c.label}</td><td className="text-right font-mono">{c.format(game.away_features![c.key] as number)}</td><td className="text-right font-mono">{c.format(game.home_features![c.key] as number)}</td></tr>)}</tbody>
            </table></div>
            <p className="text-xs leading-relaxed text-slate-500">Rolling history carries across seasons; Elo regresses one-third toward average each offseason. Injuries, starting quarterbacks, weather and betting prices are not model inputs. This is not a betting recommendation or an exact-score model.</p>
          </div> : <p className="p-7 text-amber-200">Prediction withheld: kickoff or historical team coverage is missing.</p>}
        </>}
      </article>
    </section>

    {evaluation && <section className="rounded-xl border border-slate-800 p-5 sm:p-7">
      <h2 className="text-xl font-semibold">Does it beat the simple model?</h2>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-400">A regularized logistic model is fitted on earlier seasons only, then tested on the entire next season. Team features update using prior-day results. These are retrospective tests on today’s corrected history, not a prospective accuracy claim.</p>
      <div className="mt-5 overflow-x-auto"><table className="w-full min-w-[550px] text-sm">
        <thead><tr className="text-left text-slate-500">{["Test season","Games","Model accuracy","Elo accuracy","Model Brier","Elo Brier"].map(v => <th className="pb-3 font-normal" key={v}>{v}</th>)}</tr></thead>
        <tbody>{evaluation.seasons.map(r => <tr key={r.season} className="border-t border-slate-800"><td className="py-3">{r.season}</td><td>{r.candidate.n}</td><td>{pct(r.candidate.accuracy)}</td><td>{pct(r.elo.accuracy)}</td><td className="font-mono">{r.candidate.brier.toFixed(4)}</td><td className="font-mono">{r.elo.brier.toFixed(4)}</td></tr>)}</tbody>
      </table></div>
      <p className="mt-4 text-sm text-amber-200">{evaluation.candidate.brier < evaluation.elo.brier ? "The candidate has a lower pooled Brier score in this retrospective sample. That alone does not qualify it for promotion." : "The candidate does not beat Elo on pooled Brier score. It remains experimental; the production model is unchanged."}</p>
      <details className="mt-5 rounded-lg bg-slate-900 p-4"><summary className="cursor-pointer text-sm">Probability reliability & validation details</summary>
        <p className="mt-3 text-xs text-slate-400">Home-win probability buckets. Small buckets are noisy. Ties are excluded from binary evaluation but count as half a win when updating history. Preseason is excluded; playoffs are included. No random train/test split, future score, closing line or final-season aggregate is used as an input.</p>
        <div className="mt-3 overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-slate-500"><th>Bucket</th><th>Games</th><th>Mean prediction</th><th>Observed wins</th></tr></thead><tbody>{evaluation.reliability.map(r => <tr key={r.range}><td className="py-2">{r.range}</td><td>{r.n}</td><td>{pct(r.predicted)}</td><td>{pct(r.observed)}</td></tr>)}</tbody></table></div>
        <p className="mt-3 text-xs text-slate-500">Pooled log loss: model {evaluation.candidate.log_loss.toFixed(4)} · Elo {evaluation.elo.log_loss.toFixed(4)}. Training-only home-win-rate baseline: Brier {evaluation.home_prior.brier.toFixed(4)}.</p>
      </details>
    </section>}
    <footer className="text-xs leading-relaxed text-slate-500">
      Recipe: regularized logistic regression · artifact {data.version || "unavailable"} · {data.new_results_applied ?? 0} newer finalized games applied to team features. Retraining is manual; no automatic promotion.<br />
      Concept inspired by <a className="underline" href="https://www.axonlearn.app/nfl">Axon’s public football notebook description</a> and the <a className="underline" href="https://www.instagram.com/reel/DdAuAvmhRrU/">linked demonstration</a>. Independently implemented; not affiliated. Data: <a className="underline" href="https://github.com/nflverse/nfldata">nflverse</a> and the app’s NFL schedule.
    </footer>
  </div>;
}
