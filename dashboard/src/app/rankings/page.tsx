"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { RankingRow } from "@/lib/types";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui";

const SPORTS = ["nfl", "ncaaf", "nba", "wnba", "ncaam", "nhl", "mlb", "ncaabaseball"];

export default function RankingsPage() {
  const [sport, setSport] = useState("wnba");
  const { data, error, isLoading } = useSWR<RankingRow[]>(`/rankings/${sport}`, fetcher, {
    refreshInterval: 300_000,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Power Rankings</h1>
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
      </div>

      {isLoading && <LoadingState />}
      {error && <ErrorState message={error.message} />}
      {data && data.length === 0 && (
        <EmptyState message="No ratings yet - ValueAgent hasn't evaluated any games for this sport." />
      )}

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-left text-xs uppercase text-gray-500">
            <tr>
              <th className="px-3 py-2">#</th>
              <th className="px-3 py-2">Team</th>
              <th className="px-3 py-2">ELO</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((r) => (
              <tr key={r.team_id} className="border-t border-border">
                <td className="px-3 py-2 text-gray-500">{r.rank}</td>
                <td className="px-3 py-2">{r.team_name}</td>
                <td className="px-3 py-2 font-mono">{r.elo_rating.toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
