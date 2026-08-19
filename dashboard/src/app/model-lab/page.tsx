import { Card } from "@/components/ui";

const SPORTS = ["NFL", "NBA", "MLB", "NHL", "NCAAF"];

export default function ModelLabPage() {
  return <div className="space-y-5"><header><p className="eyebrow">Evaluation</p><h1 className="mt-2 text-2xl font-semibold text-gray-100">Model lab</h1><p className="mt-2 text-sm text-gray-400">Coverage and calibration are release gates, not decorations. Metrics will populate from retained snapshots and paper outcomes.</p></header><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{SPORTS.map((sport) => <Card key={sport}><p className="text-xs uppercase tracking-wide text-gray-500">{sport}</p><p className="mt-3 text-sm text-gray-400">Awaiting validated coverage</p></Card>)}</div></div>;
}
