"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Game } from "@/lib/types";
import { Card, LoadingState, ErrorState, EmptyState } from "@/components/ui";

const SPORTS = ["nfl", "ncaaf", "nba", "wnba", "ncaam", "nhl", "mlb", "ncaabaseball"];

function formatGameTime(iso: string | null): string {
  if (!iso) return "Time TBD";
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function GamesPage() {
  const [sport, setSport] = useState<string>("");
  const query = sport ? `?sport=${sport}` : "";
  // Backend default is already status=scheduled within a 7-day forward
  // window (constraint #9) - this page never asks for anything else,
  // "upcoming only" per the Phase 5 spec.
  const { data, error, isLoading } = useSWR<Game[]>(`/games${query}`, fetcher, {
    refreshInterval: 60_000,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Upcoming Games</h1>
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
      </div>

      {isLoading && <LoadingState />}
      {error && <ErrorState message={error.message} />}
      {data && data.length === 0 && <EmptyState message="No upcoming games in the next 7 days." />}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data?.map((g) => (
          <Card key={g.id} className="space-y-1">
            <span className="text-xs uppercase text-gray-500">{g.sport}</span>
            <p className="font-medium">
              {g.away_team_name} @ {g.home_team_name}
            </p>
            <p className="text-sm text-gray-400">{formatGameTime(g.game_time)}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}
