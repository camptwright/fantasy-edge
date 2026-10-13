"use client";
import { useState } from "react";
import { american, bookLabel, percent, signedPct, statLabel, type Parlay, type ParlayResult } from "@/lib/props";

const EXAMPLES = ["Safe 3-leg parlay, overs only", "4 leg value parlay on receivers", "Same-game parlay for the Chiefs game", "2 leg unders on rushing yards"];
const STATUS: Record<string, string> = {
  no_board: "No current props on the board yet. Books post most NFL props midweek.",
  no_candidates: "No props match that request. Try fewer filters.",
  constraints_unmet: "Not enough legs at a single book for that request (a parlay must be placed at one book). Try fewer legs or allow same-game legs.",
};

export function ParlayCard({ parlay, index }: { parlay: Parlay; index: number }) {
  return <article className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
    <header className="flex flex-wrap items-baseline justify-between gap-2">
      <h3 className="font-semibold">{index === 0 ? "Best" : `Option ${index + 1}`} · {bookLabel(parlay.book)} <span className="text-sm font-normal text-slate-400">{parlay.legs.length} legs{parlay.same_game ? " · same game" : ""}</span></h3>
      <p className="tabular-nums"><span className="text-lg font-semibold">{american(parlay.american)}</span> <span className="text-xs text-slate-500">as priced leg by leg</span></p>
    </header>
    <dl className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
      <div className="rounded-lg bg-slate-950/60 p-2"><dt className="text-slate-500">Hit chance</dt><dd className="mt-0.5 text-base font-semibold tabular-nums">{percent(parlay.probability, 1)}</dd>
        {parlay.probability !== parlay.independent_probability && <dd className="text-[10px] text-slate-500">{percent(parlay.independent_probability, 1)} if independent</dd>}</div>
      <div className="rounded-lg bg-slate-950/60 p-2"><dt className="text-slate-500">Fair odds</dt><dd className="mt-0.5 text-base font-semibold tabular-nums">{american(parlay.fair_american)}</dd></div>
      <div className="rounded-lg bg-slate-950/60 p-2"><dt className="text-slate-500">{parlay.same_game ? "Price to beat" : "EV"}</dt>
        <dd className={`mt-0.5 text-base font-semibold tabular-nums ${parlay.ev != null && parlay.ev > 0 ? "text-emerald-300" : ""}`}>{parlay.same_game ? american(parlay.fair_american) : signedPct(parlay.ev)}</dd></div>
    </dl>
    <ol className="mt-3 space-y-2">{parlay.legs.map(leg => <li key={leg.id} className="rounded-lg border border-slate-800 p-3 text-sm">
      <p className="flex flex-wrap items-baseline justify-between gap-2"><span className="font-medium">{leg.player} {leg.side} {leg.line} {statLabel(leg.stat).toLowerCase()}</span>
        <span className="tabular-nums">{american(leg.price)} <span className="text-[11px] text-slate-500">fair {percent(leg.fair)}</span></span></p>
      <p className="text-[11px] text-slate-500">{leg.position} · {leg.matchup}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-slate-400">{leg.reasons.map(r => <li key={r}>{r}</li>)}</ul>
    </li>)}</ol>
    {parlay.same_game && <p className="mt-2 text-xs text-amber-200/80">Same-game legs are correlated; the book reprices them. Only take it if the book&apos;s same-game price is longer than {american(parlay.fair_american)}.</p>}
  </article>;
}

/** Local-AI parlay generator: describe it; the local model reads the request and the optimizer builds it. */
export function ParlayGenerator({ sport, books }: { sport: string; books: string[] }) {
  const [prompt, setPrompt] = useState("");
  const [legs, setLegs] = useState("");
  const [mode, setMode] = useState("");
  const [side, setSide] = useState("");
  const [sameGame, setSameGame] = useState(false);
  const [book, setBook] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ParlayResult | null>(null);
  const select = "mt-1 block min-h-10 rounded-lg border border-slate-700 bg-slate-950 px-2 text-sm";
  async function run(text = prompt) {
    setBusy(true); setError(""); setResult(null);
    try {
      const body: Record<string, unknown> = { sport, prompt: text };
      if (legs) body.legs = Number(legs);
      if (mode) body.mode = mode;
      if (side) body.side = side;
      if (sameGame) body.same_game = true;
      if (book) body.books = [book];
      const response = await fetch("/api/parlays/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(50000) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The generator could not handle that request.");
      setResult(data);
    } catch (e) { setError(e instanceof Error ? e.message : "Generator unavailable"); } finally { setBusy(false); }
  }
  return <section aria-label="Parlay generator" className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
    <h2 className="text-lg font-semibold">AI parlay generator <span className="ml-1 rounded bg-violet-500/15 px-2 py-0.5 align-middle text-[11px] font-medium uppercase tracking-wider text-violet-300">Local model</span></h2>
    <p className="mt-1 text-sm text-slate-400">Describe the parlay. A model running on this server reads the request; the optimizer picks the legs at one book and prices them against the consensus.</p>
    <form className="mt-3 space-y-3" onSubmit={e => { e.preventDefault(); void run(); }}>
      <textarea value={prompt} onChange={e => setPrompt(e.target.value)} maxLength={500} rows={2} aria-label="Describe your parlay"
        placeholder="e.g. safe 3 leg parlay with Bills receivers, overs only" className="block w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm" />
      <div className="flex flex-wrap gap-2">{EXAMPLES.map(x => <button key={x} type="button" onClick={() => { setPrompt(x); void run(x); }} disabled={busy}
        className="min-h-9 rounded-full border border-slate-700 px-3 text-xs text-slate-300 hover:border-violet-400">{x}</button>)}</div>
      <div className="flex flex-wrap items-end gap-3 text-xs text-slate-400">
        <label>Legs<select value={legs} onChange={e => setLegs(e.target.value)} className={select}><option value="">From text (3)</option>{[2, 3, 4, 5, 6].map(n => <option key={n}>{n}</option>)}</select></label>
        <label>Style<select value={mode} onChange={e => setMode(e.target.value)} className={select}><option value="">From text (value)</option><option value="value">Value</option><option value="balanced">Balanced</option><option value="safe">Safe</option></select></label>
        <label>Side<select value={side} onChange={e => setSide(e.target.value)} className={select}><option value="">From text (any)</option><option value="over">Overs</option><option value="under">Unders</option></select></label>
        <label>Book<select value={book} onChange={e => setBook(e.target.value)} className={select}><option value="">Best of all</option>{books.map(b => <option key={b} value={b}>{bookLabel(b)}</option>)}</select></label>
        <label className="flex min-h-10 items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={sameGame} onChange={e => setSameGame(e.target.checked)} className="h-4 w-4" />Same-game legs</label>
        <button disabled={busy} className="min-h-10 rounded-lg bg-violet-500 px-4 text-sm font-semibold text-slate-950 hover:bg-violet-400 disabled:bg-slate-800 disabled:text-slate-500">{busy ? "Building…" : "Generate"}</button>
      </div>
    </form>
    {error && <p role="alert" className="mt-3 text-sm text-amber-300">{error}</p>}
    {result && <div aria-live="polite" className="mt-4 space-y-3">
      {result.ai && <p className="text-xs text-slate-500">{result.ai.note}{result.ai.ms != null ? ` (${(result.ai.ms / 1000).toFixed(1)}s)` : ""}
        {result.constraints && <> · Built as: {String(result.constraints.legs)} legs, {String(result.constraints.mode)}{result.constraints.side !== "any" ? `, ${String(result.constraints.side)}s` : ""}{(result.constraints.teams as string[] | undefined)?.length ? `, ${(result.constraints.teams as string[]).join("/")}` : ""}{(result.constraints.players as string[] | undefined)?.length ? `, ${(result.constraints.players as string[]).join(", ")}` : ""}{(result.constraints.stats as string[] | undefined)?.length ? `, ${(result.constraints.stats as string[]).map(statLabel).join("/")}` : ""}{result.constraints.same_game ? ", same game allowed" : ""}</>}</p>}
      {result.relaxed === "same_game" && <p className="rounded-lg border border-amber-800/60 p-3 text-xs text-amber-200">Too few games on the board to keep every leg in a different game at one book, so same-game legs are included.</p>}
      {result.parlays.length ? result.parlays.map((p, i) => <ParlayCard key={`${p.book}:${i}`} parlay={p} index={i} />)
        : <p role="status" className="rounded-xl border border-slate-800 p-4 text-sm text-slate-400">{STATUS[result.status] ?? result.note ?? "No parlay could be built."}</p>}
    </div>}
  </section>;
}
