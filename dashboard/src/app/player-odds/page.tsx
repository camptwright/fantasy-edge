"use client";

import useSWR from "swr";
import { Card, ErrorState, LoadingState } from "@/components/ui";
import { MarketTable } from "@/components/MarketTable";
import { sportsApi } from "@/lib/api";

export default function PlayerOddsPage() {
  const { data, error, isLoading } = useSWR("/v1/player-odds", () => sportsApi.playerOdds());
  return <div className="space-y-5"><header><p className="eyebrow">Markets · player</p><h1 className="mt-2 text-2xl font-semibold text-gray-100">Player odds</h1><p className="mt-2 text-sm text-gray-400">Player markets require a current event context and a calibrated distribution before an edge can qualify.</p></header><Card>{isLoading ? <LoadingState /> : error ? <ErrorState message={error.message} /> : <MarketTable items={data?.items ?? []} />}</Card></div>;
}
