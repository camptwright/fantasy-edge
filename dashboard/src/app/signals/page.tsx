"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Signal } from "@/lib/types";
import { Card, TierBadge, LoadingState, ErrorState, EmptyState, formatPrice, formatPercent } from "@/components/ui";

const SPORTS = ["nfl", "ncaaf", "nba", "wnba", "ncaam", "nhl", "mlb", "ncaabaseball"];

export default function SignalsPage() {
  const [sport, setSport] = useState<string>("");
  const [minEv, setMinEv] = useState<number>(0);

  const query = new URLSearchParams();
  if (sport) query.set("sport", sport);
  if (minEv) query.set("min_ev", String(minEv));

  const { data, error, isLoading } = useSWR<Signal[]>(
    `/signals?${query.toString()}`,
    fetcher,
    { refreshInterval: 30_000 }
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Bet Signals</h1>
        <div className="flex gap-2">
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
            value={minEv}
            onChange={(e) => setMinEv(Number(e.target.value))}
            className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
          >
            <option value={0}>Min EV: any</option>
            <option value={2}>Min EV: 2%</option>
            <option value={5}>Min EV: 5%</option>
            <option value={10}>Min EV: 10%</option>
          </select>
        </div>
      </div>

      {isLoading && <LoadingState />}
      {error && <ErrorState message={error.message} />}
      {data && data.length === 0 && <EmptyState message="No signals yet - ValueAgent hasn't flagged anything above threshold." />}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data?.map((s) => (
          <Card key={s.id} className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase text-gray-500">{s.sport} · {s.market}</span>
              <TierBadge tier={s.tier} />
            </div>
            <p className="text-sm text-gray-400">{s.matchup}</p>
            <p className="font-medium">{s.selection}</p>
            <div className="flex items-center justify-between text-sm">
              <span>{s.bookmaker}</span>
              <span className="font-mono">{formatPrice(s.price_american)}</span>
            </div>
            <div className="flex items-center justify-between border-t border-border pt-2 text-sm">
              <span className="text-gray-400">EV</span>
              <span className="font-semibold text-accent">{formatPercent(s.ev_percent)}</span>
            </div>
            <div className="flex items-center justify-between text-xs text-gray-500">
              <span>Model {formatPercent(s.model_probability * 100)}</span>
              <span>{s.confidence}</span>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
