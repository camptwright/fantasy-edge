"use client";
import { useState } from "react";

/** Never-drop switch. Drop suggestions follow it on the next snapshot (about a minute). */
export function NeverDropToggle({ leagueId, playerId, initial }: { leagueId: string; playerId: string; initial: boolean }) {
  const [on, setOn] = useState(initial);
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  async function toggle() {
    setState("saving");
    try {
      const response = await fetch("/api/workspace/never-drop", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ league_id: leagueId, player_id: playerId, on: !on }), signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error();
      setOn(!on); setState("saved");
    } catch { setState("error"); }
  }
  return <button type="button" onClick={toggle} disabled={state === "saving"} aria-pressed={on}
    className={`inline-flex min-h-11 items-center rounded-lg border px-4 text-sm ${on ? "border-emerald-500 bg-emerald-500/10 text-emerald-200" : "border-slate-700 hover:border-emerald-500"}`}>
    {on ? "Never drop ✓" : "Never drop"}
    <span className="ml-2 text-[11px] text-slate-400" role="status">{state === "saving" ? "Saving…" : state === "saved" ? "Saved · updates within a minute" : state === "error" ? "Not saved" : ""}</span>
  </button>;
}
