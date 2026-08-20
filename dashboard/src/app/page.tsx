"use client";

import useSWR from "swr";
import { OverviewPanel } from "@/components/OverviewPanel";
import { Card, ErrorState, LoadingState } from "@/components/ui";
import { sportsApi } from "@/lib/api";

export default function SportsHomePage() {
  const { data, error, isLoading } = useSWR("/v1/overview", sportsApi.overview, { refreshInterval: 60_000 });
  const { data: assistant } = useSWR("/v1/assistant-status", sportsApi.assistantStatus, { refreshInterval: 30_000 });

  return (
    <div className="space-y-6">
      <header className="max-w-3xl">
        <p className="eyebrow">Wednesday · shared workspace</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-gray-100 sm:text-3xl">A calm read on today&apos;s board.</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-gray-400">Sports keeps the evidence, freshness, and model confidence next to every market. Quiet is a valid result.</p>
      </header>
      <Card className="border-accent/20 bg-accent/[0.04]">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div><p className="eyebrow text-accent/80">Adjutant assistant</p><p className="mt-1 text-sm text-gray-300">Read-only sports reasoning uses the shared local-first assistant route.</p></div>
          <span className={assistant?.active ? "text-xs text-accent" : "text-xs text-gray-500"}>{assistant?.active ? `Active · ${assistant.model_alias}` : "Checking…"}</span>
        </div>
      </Card>
      {isLoading && <LoadingState />}
      {error && <ErrorState message={error.message} />}
      {data && <OverviewPanel overview={data} />}
    </div>
  );
}
