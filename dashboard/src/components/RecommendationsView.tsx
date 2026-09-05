"use client";

import { useState } from "react";
import type { Prop, Signal } from "@/app/recommendations/page";

type SelectedLeg = {
  kind: "signal" | "prop";
  id: string;
  side?: "over" | "under";
  label: string;
  sport: string;
};

type BuildResult = {
  legs: unknown[];
  combined_probability: number | null;
  combined_price_american: number | null;
  skipped_legs: { kind: string; id: string; side?: string; reason: string }[];
  note: string;
};

function formatPrice(price: number | null): string {
  if (price === null) return "—";
  return price > 0 ? `+${price}` : `${price}`;
}

function formatPercent(value: number | null): string {
  if (value === null) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function legKey(leg: Pick<SelectedLeg, "kind" | "id" | "side">): string {
  return `${leg.kind}:${leg.id}:${leg.side ?? ""}`;
}

export function RecommendationsView({
  narrative,
  narrativeNote,
  generatedAgo,
  bySport,
}: {
  narrative: string | null;
  narrativeNote: string | null;
  generatedAgo: string;
  bySport: { sport: string; signals: Signal[]; props: Prop[] }[];
}) {
  const [legs, setLegs] = useState<SelectedLeg[]>([]);
  const [result, setResult] = useState<BuildResult | null>(null);
  const [loading, setLoading] = useState(false);
  // Below lg, the slip lives as a fixed bottom sheet, not a sidebar - the
  // page is 5 sports of stacked tables tall, and a sidebar that only
  // appears after all of them would mean scrolling past everything just to
  // see what you've picked. Collapsed by default; a leg add auto-expands
  // it once so a first-time mobile user notices it exists at all.
  const [mobileSlipOpen, setMobileSlipOpen] = useState(false);

  function addLeg(leg: SelectedLeg) {
    setLegs((prev) => {
      if (prev.some((l) => legKey(l) === legKey(leg))) return prev;
      return [...prev, leg];
    });
    setResult(null);
    setMobileSlipOpen(true);
  }

  function removeLeg(leg: SelectedLeg) {
    setLegs((prev) => prev.filter((l) => legKey(l) !== legKey(leg)));
    setResult(null);
  }

  async function calculate() {
    setLoading(true);
    try {
      const res = await fetch("/api/parlays/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          legs: legs.map((l) => ({ kind: l.kind, id: l.id, side: l.side ?? null })),
        }),
      });
      setResult(res.ok ? await res.json() : null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0">
        <section className="mb-8 rounded-lg border border-slate-700 bg-slate-900/40 p-5">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm uppercase text-slate-500">Market briefing</h2>
            <span className="text-xs text-slate-500">Generated {generatedAgo}</span>
          </div>
          {narrative ? (
            <p className="whitespace-pre-wrap text-sm text-slate-300">{narrative}</p>
          ) : (
            <p className="text-sm text-slate-500">{narrativeNote ?? "No narrative yet."}</p>
          )}
        </section>

        {bySport.map(({ sport, signals: topSignals, props: topProps }) => {
          if (topSignals.length === 0 && topProps.length === 0) return null;

          return (
            <section key={sport} className="mb-10">
              <h2 className="mb-3 text-2xl font-semibold uppercase">{sport}</h2>
              <div className="grid gap-6 lg:grid-cols-2">
                <div className="min-w-0">
                  <h3 className="mb-2 text-sm uppercase text-slate-500">Game lines</h3>
                  {topSignals.length === 0 ? (
                    <p className="rounded-lg border border-slate-700 p-4 text-sm text-slate-400">
                      No priced signals yet.
                    </p>
                  ) : (
                    <div className="overflow-x-auto rounded-lg border border-slate-700">
                      <table className="w-full min-w-[480px] text-left text-sm">
                        <thead className="border-b border-slate-700 text-xs uppercase text-slate-500">
                          <tr>
                            <th className="px-3 py-2">Selection</th>
                            <th className="px-3 py-2">Price</th>
                            <th className="px-3 py-2">EV%</th>
                            <th className="px-3 py-2" />
                          </tr>
                        </thead>
                        <tbody>
                          {topSignals.map((signal) => (
                            <tr key={signal.id} className="border-b border-slate-800 last:border-0">
                              <td className="px-3 py-2 text-slate-200">
                                {signal.selection}
                                <div className="text-xs text-slate-500">{signal.matchup}</div>
                              </td>
                              <td className="px-3 py-2 font-mono text-slate-300">
                                {formatPrice(signal.price_american)}
                              </td>
                              <td className="px-3 py-2 font-mono text-emerald-400">
                                {signal.ev_percent.toFixed(1)}%
                              </td>
                              <td className="px-3 py-2">
                                <button
                                  onClick={() =>
                                    addLeg({ kind: "signal", id: signal.id, label: signal.selection, sport })
                                  }
                                  className="rounded-md border border-emerald-700 px-2 py-1 text-xs text-emerald-300 hover:bg-emerald-900/40"
                                >
                                  Add
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
                <div className="min-w-0">
                  <h3 className="mb-2 text-sm uppercase text-slate-500">Player props</h3>
                  {topProps.length === 0 ? (
                    <p className="rounded-lg border border-slate-700 p-4 text-sm text-slate-400">
                      No qualified props yet.
                    </p>
                  ) : (
                    <div className="overflow-x-auto rounded-lg border border-slate-700">
                      <table className="w-full min-w-[480px] text-left text-sm">
                        <thead className="border-b border-slate-700 text-xs uppercase text-slate-500">
                          <tr>
                            <th className="px-3 py-2">Player</th>
                            <th className="px-3 py-2">Proj</th>
                            <th className="px-3 py-2">Over</th>
                            <th className="px-3 py-2">Under</th>
                          </tr>
                        </thead>
                        <tbody>
                          {topProps.map((prop) => (
                            <tr key={prop.id} className="border-b border-slate-800 last:border-0">
                              <td className="px-3 py-2 text-slate-200">
                                {prop.player_name}
                                <div className="text-xs text-slate-500">
                                  {prop.stat_type} · line {prop.line}
                                </div>
                              </td>
                              <td className="px-3 py-2 font-mono text-slate-400">
                                {prop.projection !== null ? prop.projection.toFixed(1) : "—"}
                              </td>
                              <td className="px-3 py-2">
                                <button
                                  disabled={prop.over_price_american === null || prop.edge_percent === null}
                                  onClick={() =>
                                    addLeg({
                                      kind: "prop",
                                      id: prop.id,
                                      side: "over",
                                      label: `${prop.player_name} Over ${prop.line} ${prop.stat_type}`,
                                      sport,
                                    })
                                  }
                                  className="rounded-md border border-emerald-700 px-2 py-1 text-xs text-emerald-300 hover:bg-emerald-900/40 disabled:opacity-30"
                                >
                                  O {formatPrice(prop.over_price_american)}
                                  {prop.edge_percent !== null ? ` (${prop.edge_percent.toFixed(1)}%)` : ""}
                                </button>
                              </td>
                              <td className="px-3 py-2">
                                <button
                                  disabled={prop.under_price_american === null || prop.under_edge_percent === null}
                                  onClick={() =>
                                    addLeg({
                                      kind: "prop",
                                      id: prop.id,
                                      side: "under",
                                      label: `${prop.player_name} Under ${prop.line} ${prop.stat_type}`,
                                      sport,
                                    })
                                  }
                                  className="rounded-md border border-slate-600 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800 disabled:opacity-30"
                                >
                                  U {formatPrice(prop.under_price_american)}
                                  {prop.under_edge_percent !== null ? ` (${prop.under_edge_percent.toFixed(1)}%)` : ""}
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </div>
            </section>
          );
        })}
      </div>

      <aside
        className={`fixed inset-x-0 bottom-0 z-40 max-h-[75vh] overflow-y-auto rounded-t-2xl border-t border-slate-700 bg-slate-950 shadow-2xl transition-transform duration-200 lg:static lg:top-6 lg:h-fit lg:max-h-none lg:translate-y-0 lg:overflow-visible lg:rounded-lg lg:border lg:border-slate-700 lg:bg-slate-900/40 lg:shadow-none ${
          mobileSlipOpen ? "translate-y-0" : "translate-y-[calc(100%-3.25rem)]"
        }`}
      >
        <button
          type="button"
          onClick={() => setMobileSlipOpen((open) => !open)}
          className="flex w-full items-center justify-between px-4 py-3 text-sm font-semibold text-slate-100 lg:hidden"
          aria-expanded={mobileSlipOpen}
        >
          <span>Parlay slip{legs.length > 0 ? ` · ${legs.length} leg${legs.length === 1 ? "" : "s"}` : ""}</span>
          <span className="text-slate-500">{mobileSlipOpen ? "Hide ▾" : "Show ▴"}</span>
        </button>

        <div className="px-4 pb-4 lg:sticky lg:top-6 lg:p-4">
          <h2 className="mb-3 hidden text-sm uppercase text-slate-500 lg:block">Parlay slip</h2>
          {legs.length === 0 ? (
            <p className="text-sm text-slate-500">Add signals or props to build a parlay.</p>
          ) : (
            <ul className="mb-4 space-y-2">
              {legs.map((leg) => (
                <li
                  key={legKey(leg)}
                  className="flex items-center justify-between gap-2 rounded-md border border-slate-800 p-2 text-sm"
                >
                  <span className="text-slate-300">{leg.label}</span>
                  <button onClick={() => removeLeg(leg)} className="text-xs text-red-400 hover:text-red-300">
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
          <button
            onClick={calculate}
            disabled={legs.length === 0 || loading}
            className="w-full rounded-md bg-emerald-600 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-emerald-500 disabled:opacity-30"
          >
            {loading ? "Calculating…" : "Calculate parlay"}
          </button>
          {result && (
            <div className="mt-4 space-y-2 border-t border-slate-800 pt-4 text-sm">
              {result.combined_probability !== null ? (
                <>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Combined probability</span>
                    <span className="font-mono text-emerald-300">{formatPercent(result.combined_probability)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Combined price</span>
                    <span className="font-mono text-emerald-300">{formatPrice(result.combined_price_american)}</span>
                  </div>
                </>
              ) : (
                <p className="text-slate-500">{result.note}</p>
              )}
              {result.skipped_legs.length > 0 && (
                <p className="text-xs text-amber-400">
                  {result.skipped_legs.length} leg(s) could not be priced and were skipped.
                </p>
              )}
              <p className="text-xs text-slate-600">Legs assumed independent - not a correlated joint model.</p>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
