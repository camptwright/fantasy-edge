"use client";

import { useState } from "react";
import { DfsBuilder } from "./dfs-builder";
import { ProjectionsView } from "./projections-view";
import { StartSitView, WaiversView } from "./start-sit-waivers";

type Tab = "dfs" | "projections" | "start-sit" | "waivers";

const TABS: { id: Tab; label: string }[] = [
  { id: "dfs", label: "DFS Builder" },
  { id: "projections", label: "Projections" },
  { id: "start-sit", label: "Start/Sit" },
  { id: "waivers", label: "Waivers" },
];

export default function FantasyPage() {
  const [tab, setTab] = useState<Tab>("dfs");

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">Fantasy</h1>
        <div className="flex rounded-md border border-border">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-1.5 text-sm ${
                tab === t.id ? "bg-accent/10 text-accent" : "text-gray-400"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === "dfs" && <DfsBuilder />}
      {tab === "projections" && <ProjectionsView />}
      {tab === "start-sit" && <StartSitView />}
      {tab === "waivers" && <WaiversView />}
    </div>
  );
}
