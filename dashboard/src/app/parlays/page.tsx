"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { fetcher, apiPost, ApiError } from "@/lib/api";
import { AssistantStatus, BestPropLine, Parlay } from "@/lib/types";
import { Card, LoadingState, ErrorState, EmptyState, formatPercent } from "@/components/ui";

const SPORTS = ["nfl", "ncaaf", "nba", "wnba", "ncaam", "nhl", "mlb", "ncaabaseball"];

const RESULT_STYLES: Record<string, string> = {
  win: "text-accent",
  loss: "text-red-400",
  push: "text-gray-400",
};

export default function ParlaysPage() {
  const [sport, setSport] = useState("");
  const [numLegs, setNumLegs] = useState(3);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"build" | "history">("build");

  const { data, error, isLoading, mutate } = useSWR<Parlay[]>("/parlays", fetcher, {
    refreshInterval: 60_000,
  });
  const propsQuery = sport ? `?sport=${encodeURIComponent(sport)}` : "";
  const { data: board, error: boardError, isLoading: boardLoading } = useSWR<BestPropLine[]>(
    `/props/best${propsQuery}`,
    fetcher,
    { refreshInterval: 60_000 },
  );
  const { data: assistant } = useSWR<AssistantStatus>("/v1/assistant-status", fetcher, { refreshInterval: 30_000 });

  const visibleBoard = useMemo(() => board?.slice(0, 8) ?? [], [board]);

  async function handleGenerate() {
    setGenerating(true);
    setGenError(null);
    try {
      await apiPost("/parlays/generate", { sport: sport || null, num_legs: numLegs });
      await mutate();
    } catch (e) {
      // CONSTRAINT #12: this legitimately 503s until the shared LiteLLM key is set -
      // that's a real, surfaced error, not a bug to hide.
      setGenError(e instanceof ApiError ? e.message : "Failed to generate parlay");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="space-y-3">
        <p className="eyebrow">Research desk · parlay builder</p>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-gray-100 sm:text-3xl">Build a considered card.</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-400">
              Adjutant weighs the freshest permitted player-prop lines and returns a paper parlay for review.
              Nothing here places a wager.
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-2 text-xs text-gray-400" aria-live="polite">
            <span className={`h-2 w-2 rounded-full ${assistant?.active ? "bg-accent" : "bg-amber-400"}`} />
            {assistant?.active ? `Adjutant · ${assistant.model_alias}` : "Assistant checking"}
          </div>
        </div>
      </header>

      <div className="flex gap-1 border-b border-border" role="tablist" aria-label="Parlay workspace">
        {(["build", "history"] as const).map((tab) => (
          <button key={tab} type="button" role="tab" aria-selected={activeTab === tab} onClick={() => setActiveTab(tab)}
            className={`min-h-11 border-b-2 px-3 text-sm capitalize transition-colors ${activeTab === tab ? "border-accent text-accent" : "border-transparent text-gray-500 hover:text-gray-200"}`}>
            {tab === "build" ? "Build" : "History"}
          </button>
        ))}
      </div>

      {activeTab === "build" && <>
        <Card className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="eyebrow">Configuration</p>
              <h2 className="mt-1 text-base font-medium text-gray-100">Ask for a paper parlay</h2>
            </div>
            <span className="rounded-full bg-accent/10 px-2.5 py-1 text-xs text-accent">Local-first reasoning</span>
          </div>
          <p className="max-w-2xl text-sm leading-6 text-gray-400">
            The assistant sees current lines and source disagreement. It can only use candidates retained by the
            Fantasy Edge API, and will decline when coverage or calibration is insufficient.
          </p>
          <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <label className="grid gap-1.5 text-xs text-gray-400">
              Sport
              <select value={sport} onChange={(e) => setSport(e.target.value)} className="min-h-11 rounded-xl border border-border bg-bg px-3 text-sm text-gray-200 focus:border-accent focus:outline-none">
                <option value="">Any sport</option>
                {SPORTS.map((s) => <option key={s} value={s}>{s.toUpperCase()}</option>)}
              </select>
            </label>
            <label className="grid gap-1.5 text-xs text-gray-400">
              Legs
              <select value={numLegs} onChange={(e) => setNumLegs(Number(e.target.value))} className="min-h-11 rounded-xl border border-border bg-bg px-3 text-sm text-gray-200 focus:border-accent focus:outline-none">
                {[2, 3, 4].map((n) => <option key={n} value={n}>{n} legs</option>)}
              </select>
            </label>
            <button onClick={handleGenerate} disabled={generating || !assistant?.active} className="min-h-11 rounded-xl bg-accent px-4 text-sm font-semibold text-black transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50">
              {generating ? "Reasoning…" : "Build with Adjutant"}
            </button>
          </div>
          {!assistant?.active && <p className="text-xs text-amber-300">The assistant is unavailable. Try again when the local-first route reports active.</p>}
          {genError && <ErrorState message={genError} />}
        </Card>

        <section className="space-y-3" aria-labelledby="board-heading">
          <div className="flex items-end justify-between gap-3">
            <div><p className="eyebrow">Candidate board</p><h2 id="board-heading" className="mt-1 text-lg font-medium text-gray-100">Current source disagreement</h2></div>
            <span className="text-xs text-gray-500">{board?.length ?? 0} tracked</span>
          </div>
          {boardLoading && <LoadingState />}
          {boardError && <ErrorState message={boardError.message} />}
          {!boardLoading && !boardError && visibleBoard.length === 0 && <Card><EmptyState message="No cross-source player lines are available for this filter yet." /></Card>}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {visibleBoard.map((prop) => <Card key={prop.id} className="space-y-3">
              <div className="flex items-start justify-between gap-2"><span className="text-xs uppercase tracking-wide text-gray-500">{prop.sport}</span><span className="rounded-full bg-accent/10 px-2 py-1 text-[11px] text-accent">spread {prop.cross_source_spread.toFixed(1)}</span></div>
              <div><p className="font-medium text-gray-100">{prop.player_name}</p><p className="mt-1 text-sm text-gray-400">{prop.stat_type}</p></div>
              {prop.matchup && <p className="text-xs text-gray-500">{prop.matchup}</p>}
              <div className="space-y-1 border-t border-border pt-2 text-xs">{prop.sources.map((source) => <div key={source.source} className="flex justify-between gap-2"><span className="text-gray-500">{source.source}</span><span className="font-mono text-gray-300">{source.line}</span></div>)}</div>
            </Card>)}
          </div>
        </section>
      </>}

      {activeTab === "history" && <section className="space-y-3" aria-labelledby="history-heading">
        <div><p className="eyebrow">Saved research</p><h2 id="history-heading" className="mt-1 text-lg font-medium text-gray-100">Generated parlays</h2></div>
        {isLoading && <LoadingState />}
        {error && <ErrorState message={error.message} />}
        {data && data.length === 0 && <Card><EmptyState message="No parlays generated yet." /></Card>}
        <div className="grid gap-3 sm:grid-cols-2">
          {data?.map((p) => (
            <Card key={p.id} className="space-y-3">
              <div className="flex items-center justify-between gap-2"><span className="text-xs uppercase tracking-wide text-gray-500">{p.sport ?? "multi-sport"}</span>{p.result && <span className={`text-xs font-medium uppercase ${RESULT_STYLES[p.result] ?? "text-gray-400"}`}>{p.result}</span>}</div>
              <div><p className="font-medium text-gray-100">{p.title ?? "Untitled parlay"}</p>{p.rationale && <p className="mt-2 text-sm leading-6 text-gray-400">{p.rationale}</p>}</div>
              {p.legs && p.legs.length > 0 && <ul className="space-y-2 border-t border-border pt-3 text-sm">{p.legs.map((leg) => <li key={leg.id} className="flex items-center justify-between gap-3"><span className="text-gray-300">{leg.description}</span>{leg.price_american !== null && <span className="font-mono text-gray-500">{leg.price_american > 0 ? `+${leg.price_american}` : leg.price_american}</span>}</li>)}</ul>}
              <div className="flex justify-between border-t border-border pt-3 text-sm"><span className="text-gray-500">Estimated EV</span><span className="font-semibold text-accent">{formatPercent(p.ev_percent)}</span></div>
              {p.generator && <p className="text-[11px] text-gray-600">Generated by {p.generator}</p>}
            </Card>
          ))}
        </div>
      </section>}
    </div>
  );
}
