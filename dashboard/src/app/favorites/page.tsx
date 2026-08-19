import { Card, EmptyState } from "@/components/ui";

export default function FavoritesPage() {
  return <div className="space-y-5"><header><p className="eyebrow">Shared workspace</p><h1 className="mt-2 text-2xl font-semibold text-gray-100">Favorites</h1><p className="mt-2 text-sm text-gray-400">One shared list for this homelab. Save teams and players to keep their next relevant market close.</p></header><Card><EmptyState message="No teams or players saved yet." /></Card></div>;
}
