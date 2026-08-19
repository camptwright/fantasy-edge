"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { Card, EmptyState, ErrorState, LoadingState, StatusBadge, formatPrice } from "@/components/ui";
import { sportsApi } from "@/lib/api";
import type { MarketAssessment } from "@/lib/types";

const SPORTS = ["nfl", "ncaaf", "nba", "wnba", "ncaam", "nhl", "mlb", "ncaabaseball"];
type SourceGroup = { source: string; lines: MarketAssessment[] };
type PlayerGroup = { name: string; sport: string; markets: SourceGroup[] };

function groupPlayers(items: MarketAssessment[]): PlayerGroup[] {
  const players = new Map<string, PlayerGroup>();
  for (const item of items) {
    const name = item.player_name ?? item.selection.replace(/\s+(OVER|UNDER)\s+[-\d.]+$/, "");
    const key = `${item.sport}:${name}`;
    const player = players.get(key) ?? { name, sport: item.sport, markets: [] };
    const source = item.bookmaker ?? "Unknown source";
    const sourceGroup = player.markets.find((entry) => entry.source === source);
    if (sourceGroup) sourceGroup.lines.push(item);
    else player.markets.push({ source, lines: [item] });
    players.set(key, player);
  }
  return [...players.values()].sort((a, b) => a.name.localeCompare(b.name));
}

export default function PlayerOddsPage() {
  const [sport, setSport] = useState("");
  const [source, setSource] = useState("");
  const [market, setMarket] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const query = new URLSearchParams();
  if (sport) query.set("sport", sport);
  if (source) query.set("source", source);
  const queryString = query.toString() ? `?${query.toString()}` : "";
  const { data, error, isLoading } = useSWR(`/v1/player-odds${queryString}`, () => sportsApi.playerOdds(queryString), { refreshInterval: 60_000 });
  const sourceOptions = useMemo(() => [...new Set((data?.items ?? []).map((item) => item.bookmaker).filter(Boolean))] as string[], [data]);
  const marketOptions = useMemo(() => [...new Set((data?.items ?? []).map((item) => item.market))], [data]);
  const players = useMemo(() => groupPlayers(market ? (data?.items ?? []).filter((item) => item.market === market) : data?.items ?? []), [data, market]);

  return (
    <div className="space-y-5">
      <header><p className="eyebrow">Markets · player</p><h1 className="mt-2 text-2xl font-semibold text-gray-100">Player odds</h1><p className="mt-2 max-w-2xl text-sm text-gray-400">Players stay compact until you open one. Each source keeps its own observed line so differences remain visible.</p></header>
      <div className="flex flex-wrap gap-2" aria-label="Player market filters">
        <select value={sport} onChange={(event) => setSport(event.target.value)} className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-gray-200" aria-label="Filter by sport"><option value="">All sports</option>{SPORTS.map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}</select>
        <select value={source} onChange={(event) => setSource(event.target.value)} className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-gray-200" aria-label="Filter by source"><option value="">All sources</option>{sourceOptions.map((value) => <option key={value} value={value}>{value}</option>)}</select>
        <select value={market} onChange={(event) => setMarket(event.target.value)} className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-gray-200" aria-label="Filter by market"><option value="">All markets</option>{marketOptions.map((value) => <option key={value} value={value}>{value.replace("player_", "")}</option>)}</select>
      </div>
      <Card>
        {isLoading ? <LoadingState /> : error ? <ErrorState message={error.message} /> : !players.length ? <EmptyState message="No player lines match these filters." /> : <div className="divide-y divide-border/70">
          {players.map((player) => { const key = `${player.sport}:${player.name}`; const isOpen = expanded === key; return <section key={key}>
            <button type="button" onClick={() => setExpanded(isOpen ? null : key)} aria-expanded={isOpen} className="flex min-h-14 w-full items-center justify-between gap-4 py-3 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"><span><span className="font-medium text-gray-100">{player.name}</span><span className="ml-2 text-xs uppercase text-gray-500">{player.sport}</span></span><span className="text-xs text-gray-500">{player.markets.length} source{player.markets.length === 1 ? "" : "s"} <span className="ml-2 text-accent">{isOpen ? "−" : "+"}</span></span></button>
            {isOpen && <div className="pb-4 pl-3 pr-1 sm:pl-5"><ul className="space-y-2">{player.markets.map((entry) => <li key={entry.source} className="rounded-md border border-border/70 bg-black/10 p-3"><div className="mb-2 flex items-center justify-between gap-2"><span className="text-sm font-medium text-gray-200">{entry.source}</span><StatusBadge status={entry.lines[0]?.status ?? "coverage_incomplete"} /></div><div className="grid gap-2 text-sm sm:grid-cols-2">{entry.lines.map((line) => <div key={line.id} className="flex items-center justify-between rounded border border-border/50 px-2 py-2"><span className="text-gray-300">{line.side?.toUpperCase()} {line.line ?? "—"}</span><span className="font-mono text-gray-400">{formatPrice(line.price_american)}</span></div>)}</div></li>)}</ul></div>}
          </section>; })}
        </div>}
      </Card>
    </div>
  );
}
