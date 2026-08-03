"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Projection } from "@/lib/types";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui";

const SPORTS = ["nfl", "ncaaf", "nba", "wnba", "ncaam", "nhl", "mlb", "ncaabaseball"];

export function ProjectionsView() {
  const [sport, setSport] = useState("wnba");
  const { data, error, isLoading } = useSWR<Projection[]>(
    `/fantasy/projections/${sport}`,
    fetcher,
    { refreshInterval: 60_000 }
  );

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-400">
        Derived from current Underdog lines - a market-implied projection, not the
        recency-weighted model (that needs a boxscore history this system doesn&apos;t
        ingest yet).
      </p>
      <select
        value={sport}
        onChange={(e) => setSport(e.target.value)}
        className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
      >
        {SPORTS.map((s) => (
          <option key={s} value={s}>
            {s.toUpperCase()}
          </option>
        ))}
      </select>

      {isLoading && <LoadingState />}
      {error && <ErrorState message={error.message} />}
      {data && data.length === 0 && <EmptyState message="No prop lines for this sport yet." />}

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-xs uppercase text-gray-500">
            <tr>
              <th className="px-3 py-2">Player</th>
              <th className="px-3 py-2">Stat</th>
              <th className="px-3 py-2">Projected</th>
              <th className="px-3 py-2">Source</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((p, i) => (
              <tr key={`${p.player_name}-${p.stat_type}-${i}`} className="border-t border-border">
                <td className="px-3 py-2">{p.player_name}</td>
                <td className="px-3 py-2 text-gray-400">{p.stat_type}</td>
                <td className="px-3 py-2 font-mono">{p.projected_value}</td>
                <td className="px-3 py-2 text-gray-500">{p.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
