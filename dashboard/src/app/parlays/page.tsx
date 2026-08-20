"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher, apiPost, ApiError } from "@/lib/api";
import { Parlay } from "@/lib/types";
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

  const { data, error, isLoading, mutate } = useSWR<Parlay[]>("/parlays", fetcher, {
    refreshInterval: 60_000,
  });

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
    <div className="space-y-5">
      <h1 className="text-lg font-semibold">Parlays</h1>

      <Card className="space-y-3">
        <p className="text-sm text-gray-400">
          Generates a parlay from current player-prop edges via the shared local-first assistant - never requires an
          existing bet signal.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={sport}
            onChange={(e) => setSport(e.target.value)}
            className="rounded-md border border-border bg-bg px-2 py-1 text-sm"
          >
            <option value="">Any sport</option>
            {SPORTS.map((s) => (
              <option key={s} value={s}>
                {s.toUpperCase()}
              </option>
            ))}
          </select>
          <select
            value={numLegs}
            onChange={(e) => setNumLegs(Number(e.target.value))}
            className="rounded-md border border-border bg-bg px-2 py-1 text-sm"
          >
            {[2, 3, 4].map((n) => (
              <option key={n} value={n}>
                {n} legs
              </option>
            ))}
          </select>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-black disabled:opacity-50"
          >
            {generating ? "Generating…" : "Generate Parlay"}
          </button>
        </div>
        {genError && <ErrorState message={genError} />}
      </Card>

      {isLoading && <LoadingState />}
      {error && <ErrorState message={error.message} />}
      {data && data.length === 0 && <EmptyState message="No parlays generated yet." />}

      <div className="grid gap-3 sm:grid-cols-2">
        {data?.map((p) => (
          <Card key={p.id} className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase text-gray-500">{p.sport ?? "multi-sport"}</span>
              {p.result && (
                <span className={`text-xs font-medium uppercase ${RESULT_STYLES[p.result] ?? "text-gray-400"}`}>
                  {p.result}
                </span>
              )}
            </div>
            <p className="font-medium">{p.title ?? "Untitled parlay"}</p>
            {p.rationale && <p className="text-sm text-gray-400">{p.rationale}</p>}
            <div className="flex justify-between border-t border-border pt-2 text-sm">
              <span className="text-gray-400">EV</span>
              <span className="font-semibold text-accent">{formatPercent(p.ev_percent)}</span>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
