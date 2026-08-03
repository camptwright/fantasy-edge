"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { PropLine, BestPropLine } from "@/lib/types";
import { Card, LoadingState, ErrorState, EmptyState } from "@/components/ui";

const SPORTS = ["nfl", "ncaaf", "nba", "wnba", "ncaam", "nhl", "mlb", "ncaabaseball"];
// Grows as more sources come online (constraint #5: Underdog is the only
// one today). The SOURCE FILTER still needs to exist even with one option,
// per the Phase 5 spec, so a second source is a config change here, not a
// rebuild.
const SOURCES = ["underdog"];

function AllPropsView() {
  const [sport, setSport] = useState("");
  const [source, setSource] = useState("");
  const [player, setPlayer] = useState("");

  const query = new URLSearchParams();
  if (sport) query.set("sport", sport);
  if (player) query.set("player_name", player);

  const { data, error, isLoading } = useSWR<PropLine[]>(
    `/props?${query.toString()}`,
    fetcher,
    { refreshInterval: 60_000 }
  );

  // Source filtering client-side: the backend's DISTINCT ON dedup
  // (constraint #7) already runs per (player, stat, source), so filtering
  // further by source here is just a display concern, not another query.
  const rows = data?.filter((p) => !source || p.source === source) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <select
          value={sport}
          onChange={(e) => setSport(e.target.value)}
          className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
        >
          <option value="">All sports</option>
          {SPORTS.map((s) => (
            <option key={s} value={s}>
              {s.toUpperCase()}
            </option>
          ))}
        </select>
        <select
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
        >
          <option value="">All sources</option>
          {SOURCES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <input
          value={player}
          onChange={(e) => setPlayer(e.target.value)}
          placeholder="Search player…"
          className="rounded-md border border-border bg-surface px-2 py-1 text-sm placeholder:text-gray-600"
        />
      </div>

      {isLoading && <LoadingState />}
      {error && <ErrorState message={error.message} />}
      {rows.length === 0 && !isLoading && <EmptyState message="No props match these filters." />}

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-xs uppercase text-gray-500">
            <tr>
              <th className="px-3 py-2">Player</th>
              <th className="px-3 py-2">Stat</th>
              <th className="px-3 py-2">Line</th>
              <th className="px-3 py-2">Over</th>
              <th className="px-3 py-2">Under</th>
              <th className="px-3 py-2">Source</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className="border-t border-border">
                <td className="px-3 py-2">{p.player_name}</td>
                <td className="px-3 py-2 text-gray-400">{p.stat_type}</td>
                <td className="px-3 py-2 font-mono">{p.line}</td>
                <td className="px-3 py-2 font-mono">
                  {p.over_price_american ?? "—"}
                </td>
                <td className="px-3 py-2 font-mono">
                  {p.under_price_american ?? "—"}
                </td>
                <td className="px-3 py-2 text-gray-500">{p.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BestValueView() {
  const [sport, setSport] = useState("");
  const query = sport ? `?sport=${sport}` : "";
  const { data, error, isLoading } = useSWR<BestPropLine[]>(
    `/props/best${query}`,
    fetcher,
    { refreshInterval: 60_000 }
  );

  return (
    <div className="space-y-4">
      <select
        value={sport}
        onChange={(e) => setSport(e.target.value)}
        className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
      >
        <option value="">All sports</option>
        {SPORTS.map((s) => (
          <option key={s} value={s}>
            {s.toUpperCase()}
          </option>
        ))}
      </select>

      {isLoading && <LoadingState />}
      {error && <ErrorState message={error.message} />}
      {data && data.length === 0 && (
        <EmptyState message="No cross-source discrepancies yet - needs 2+ prop sources agreeing to disagree." />
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data?.map((p) => (
          <Card key={p.id} className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase text-gray-500">{p.sport}</span>
              <span className="rounded-full bg-accent/15 px-2 py-0.5 text-xs font-medium text-accent">
                spread {p.cross_source_spread.toFixed(1)}
              </span>
            </div>
            <p className="font-medium">{p.player_name}</p>
            <p className="text-sm text-gray-400">{p.stat_type}</p>
            {p.matchup && <p className="text-xs text-gray-500">{p.matchup}</p>}
            <ul className="space-y-1 border-t border-border pt-2 text-sm">
              {p.sources.map((s) => (
                <li key={s.source} className="flex justify-between">
                  <span className="text-gray-400">{s.source}</span>
                  <span className="font-mono">{s.line}</span>
                </li>
              ))}
            </ul>
          </Card>
        ))}
      </div>
    </div>
  );
}

export default function PropsPage() {
  const [tab, setTab] = useState<"best" | "all">("best");

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Player Props</h1>
        <div className="flex rounded-md border border-border">
          <button
            onClick={() => setTab("best")}
            className={`px-3 py-1.5 text-sm ${tab === "best" ? "bg-accent/10 text-accent" : "text-gray-400"}`}
          >
            Best Value
          </button>
          <button
            onClick={() => setTab("all")}
            className={`px-3 py-1.5 text-sm ${tab === "all" ? "bg-accent/10 text-accent" : "text-gray-400"}`}
          >
            All Props
          </button>
        </div>
      </div>
      {tab === "best" ? <BestValueView /> : <AllPropsView />}
    </div>
  );
}
