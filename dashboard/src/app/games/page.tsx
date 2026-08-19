"use client";

import { useState } from "react";
import useSWR from "swr";
import { MarketTable } from "@/components/MarketTable";
import { sportsApi } from "@/lib/api";
import type { SportsGame } from "@/lib/types";
import { Card, EmptyState, ErrorState, LoadingState } from "@/components/ui";

const SPORTS = ["nfl", "ncaaf", "nba", "wnba", "ncaam", "nhl", "mlb", "ncaabaseball"];

function formatGameTime(iso: string | null): string {
  if (!iso) return "Time TBD";
  return new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function GameDetails({ gameId }: { gameId: string }) {
  const { data, error, isLoading } = useSWR(`/v1/games/${gameId}`, () => sportsApi.gameDetail(gameId));
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState message={error.message} />;
  if (!data) return null;
  return <div className="space-y-4 border-t border-border/70 px-1 pb-2 pt-4 sm:px-3">
    <div><p className="eyebrow">Available markets</p><h2 className="mt-1 text-sm font-medium text-gray-200">Game lines</h2>{data.team_lines.length ? <MarketTable items={data.team_lines} /> : <EmptyState message="No game lines are available for this event yet." />}</div>
    <div><h2 className="text-sm font-medium text-gray-200">Best player props</h2>{data.player_props.length ? <MarketTable items={data.player_props} /> : <EmptyState message="No player props are linked to this event yet." />}</div>
  </div>;
}

function GameCard({ game }: { game: SportsGame }) {
  const [open, setOpen] = useState(false);
  return <Card className="p-0"><button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex min-h-24 w-full items-center justify-between gap-4 p-4 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"><span><span className="text-xs uppercase text-gray-500">{game.sport}</span><span className="mt-1 block font-medium text-gray-100">{game.away_team} @ {game.home_team}</span><span className="mt-1 block text-sm text-gray-400">{formatGameTime(game.start_time)}</span></span><span className="text-xl text-accent">{open ? "−" : "+"}</span></button>{open && <GameDetails gameId={game.id} />}</Card>;
}

export default function GamesPage() {
  const [sport, setSport] = useState("");
  const query = sport ? `?sport=${sport}` : "";
  const { data, error, isLoading } = useSWR(`/v1/games${query}`, () => sportsApi.games(query), { refreshInterval: 60_000 });
  return <div className="space-y-5"><header><p className="eyebrow">Schedule · next seven days</p><h1 className="mt-2 text-2xl font-semibold text-gray-100">Upcoming games</h1><p className="mt-2 text-sm text-gray-400">Open a game to inspect available lines and linked player props. Empty sections mean a source has not published usable coverage yet.</p></header>
    <div className="flex flex-wrap gap-2"><select value={sport} onChange={(event) => setSport(event.target.value)} className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-gray-200" aria-label="Filter games by sport"><option value="">All sports</option>{SPORTS.map((value) => <option key={value} value={value}>{value.toUpperCase()}</option>)}</select></div>
    {isLoading && <LoadingState />}{error && <ErrorState message={error.message} />}{data && data.items.length === 0 && <EmptyState message="No upcoming games in the next seven days." />}
    <div className="grid gap-3 lg:grid-cols-2">{data?.items.map((game) => <GameCard key={game.id} game={game} />)}</div>
  </div>;
}
