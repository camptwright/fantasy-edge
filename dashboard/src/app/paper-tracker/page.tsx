import { Card, EmptyState } from "@/components/ui";

export default function PaperTrackerPage() {
  return <div className="space-y-5"><header><p className="eyebrow">Research log</p><h1 className="mt-2 text-2xl font-semibold text-gray-100">Paper tracker</h1><p className="mt-2 text-sm text-gray-400">Record assumptions against immutable snapshots so later outcomes can be evaluated honestly.</p></header><Card><EmptyState message="No paper positions recorded yet." /></Card></div>;
}
