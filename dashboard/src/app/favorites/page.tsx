"use client";

import useSWR from "swr";
import { Card, EmptyState, ErrorState, LoadingState } from "@/components/ui";
import { sportsApi } from "@/lib/api";

export default function FavoritesPage() {
  const { data, error, isLoading } = useSWR("/v1/favorites", sportsApi.favorites);
  return <div className="space-y-5"><header><p className="eyebrow">Shared workspace</p><h1 className="mt-2 text-2xl font-semibold text-gray-100">Favorites</h1><p className="mt-2 text-sm text-gray-400">One shared list for this homelab. Save teams and players to keep their next relevant market close.</p></header><Card>{isLoading ? <LoadingState /> : error ? <ErrorState message={error.message} /> : data?.items.length ? <ul className="divide-y divide-border/70">{data.items.map((item) => <li key={item.id} className="flex items-center justify-between py-3"><span className="font-medium text-gray-200">{item.display_name}</span><span className="text-xs uppercase text-gray-500">{item.kind} · {item.sport}</span></li>)}</ul> : <EmptyState message="No teams or players saved yet." />}</Card></div>;
}
