"use client";

import useSWR from "swr";
import { Card, ErrorState, LoadingState } from "@/components/ui";
import { MarketTable } from "@/components/MarketTable";
import { sportsApi } from "@/lib/api";

export default function TeamOddsPage() {
  const { data, error, isLoading } = useSWR("/v1/team-odds", () => sportsApi.teamOdds());
  return <div className="space-y-5"><header><p className="eyebrow">Markets · team</p><h1 className="mt-2 text-2xl font-semibold text-gray-100">Team odds</h1><p className="mt-2 text-sm text-gray-400">Consensus views across permitted sources, with model state alongside the number.</p></header><Card>{isLoading ? <LoadingState /> : error ? <ErrorState message={error.message} /> : <MarketTable items={data?.items ?? []} />}</Card></div>;
}
