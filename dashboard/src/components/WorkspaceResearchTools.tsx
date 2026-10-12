"use client";
import { useState } from "react";
import type { ResearchContext } from "@/lib/workspace";
import { WorkspaceComparison } from "@/components/WorkspaceComparison";
import { WorkspaceTrade } from "@/components/WorkspaceTrade";

/** Avoid constructing thousands of unused select options on initial navigation. */
export function WorkspaceResearchTools({ overview }: { overview: ResearchContext }) {
  const [comparison, setComparison] = useState(false);
  const [trade, setTrade] = useState(false);
  return <div className="space-y-4">
    <button aria-expanded={comparison} aria-controls="workspace-comparison" onClick={() => setComparison(!comparison)} className="min-h-11 rounded border border-emerald-700 px-4">{comparison ? 'Close player comparison' : 'Open player comparison'}</button>
    {comparison && <div id="workspace-comparison"><WorkspaceComparison key={overview.generated_at} players={overview.comparison_players} /></div>}
    <div><button aria-expanded={trade} aria-controls="workspace-trade" onClick={() => setTrade(!trade)} className="min-h-11 rounded border border-emerald-700 px-4">{trade ? 'Close trade research' : 'Open trade research'}</button></div>
    <p className="text-xs text-slate-400">Tools use the current saved snapshot. Closing a tool clears its local selections; nothing is submitted.</p>
    {trade && <div id="workspace-trade"><WorkspaceTrade overview={overview} /></div>}
  </div>;
}
