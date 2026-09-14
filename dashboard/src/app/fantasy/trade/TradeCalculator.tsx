"use client";

import { useState } from "react";

type Player = { player_id: string; name: string; position: string | null; team: string | null; projected_points: number; custom_projected_points: number | null };
type Roster = { roster_id: number; team_name: string; is_mine: boolean; players: Player[] };
type SidePlayer = { player_id: string; name: string; position: string | null; trade_value: number };
type EvaluateResult = {
  side_a: { players: SidePlayer[]; total_value: number };
  side_b: { players: SidePlayer[]; total_value: number };
  value_difference: number;
  fairness_pct: number;
  verdict: "fair" | "side_a_favored" | "side_b_favored";
  note: string;
} | { error?: string; detail?: string };

function flatOptions(rosters: Roster[]): { player_id: string; label: string }[] {
  return rosters.flatMap((roster) => roster.players.map((player) => ({ player_id: player.player_id, label: `${roster.team_name} - ${player.name} (${player.position ?? "?"})` })));
}

function PlayerPicker({ options, onAdd }: { options: { player_id: string; label: string }[]; onAdd: (playerId: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="flex gap-2">
      <select value={value} onChange={(event) => setValue(event.target.value)} className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200">
        <option value="">Add a player…</option>
        {options.map((option) => <option key={option.player_id} value={option.player_id}>{option.label}</option>)}
      </select>
      <button
        type="button"
        onClick={() => { if (value) { onAdd(value); setValue(""); } }}
        className="shrink-0 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300 transition hover:bg-slate-800"
      >
        Add
      </button>
    </div>
  );
}

function SideEditor({ title, ids, rosters, onAdd, onRemove }: { title: string; ids: string[]; rosters: Roster[]; onAdd: (id: string) => void; onRemove: (id: string) => void }) {
  const allPlayers = rosters.flatMap((roster) => roster.players);
  const options = flatOptions(rosters).filter((option) => !ids.includes(option.player_id));
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <h3 className="font-semibold">{title}</h3>
      <div className="mt-3 space-y-2">
        {ids.length === 0 && <p className="text-sm text-slate-500">No players added yet.</p>}
        {ids.map((id) => {
          const player = allPlayers.find((candidate) => candidate.player_id === id);
          return (
            <div key={id} className="flex items-center justify-between rounded-lg bg-black/20 px-3 py-2 text-sm">
              <span>{player ? `${player.name} (${player.position ?? "?"})` : id}</span>
              <button type="button" onClick={() => onRemove(id)} className="text-slate-500 transition hover:text-red-400" aria-label={`Remove ${player?.name ?? id}`}>✕</button>
            </div>
          );
        })}
      </div>
      <div className="mt-3">
        <PlayerPicker options={options} onAdd={onAdd} />
      </div>
    </div>
  );
}

export function TradeCalculator({ leagueId, rosters }: { leagueId: string; rosters: Roster[] }) {
  const [sideA, setSideA] = useState<string[]>([]);
  const [sideB, setSideB] = useState<string[]>([]);
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [result, setResult] = useState<EvaluateResult | null>(null);

  async function evaluate() {
    setState("loading");
    try {
      const response = await fetch("/api/fantasy/trade/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ league_id: leagueId, side_a_player_ids: sideA, side_b_player_ids: sideB }),
      });
      const body: EvaluateResult = await response.json();
      setResult(body);
      setState(response.ok ? "done" : "error");
    } catch {
      setResult({ error: "Could not reach the trade service." });
      setState("error");
    }
  }

  const verdictCopy: Record<string, string> = {
    fair: "Roughly fair value on both sides.",
    side_a_favored: "Side A comes out ahead on value.",
    side_b_favored: "Side B comes out ahead on value.",
  };

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <h2 className="font-semibold">Trade calculator</h2>
      <p className="mt-1 text-xs text-slate-500">Pick any players from any team in the league - not just your own - and check the trade value on both sides.</p>
      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SideEditor title="Side A" ids={sideA} rosters={rosters} onAdd={(id) => setSideA((prev) => [...prev, id])} onRemove={(id) => setSideA((prev) => prev.filter((existing) => existing !== id))} />
        <SideEditor title="Side B" ids={sideB} rosters={rosters} onAdd={(id) => setSideB((prev) => [...prev, id])} onRemove={(id) => setSideB((prev) => prev.filter((existing) => existing !== id))} />
      </div>
      <button
        type="button"
        onClick={evaluate}
        disabled={state === "loading" || sideA.length === 0 || sideB.length === 0}
        className="mt-4 rounded-lg border border-emerald-700 bg-emerald-950/40 px-4 py-2 text-sm font-medium text-emerald-300 transition hover:bg-emerald-950/70 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {state === "loading" ? "Evaluating…" : "Evaluate trade"}
      </button>
      {result && "error" in result && (
        <p className="mt-4 rounded-lg border border-red-900 bg-red-950/30 p-3 text-sm text-red-200">{result.detail || result.error || "Something went wrong."}</p>
      )}
      {result && "verdict" in result && (
        <div className="mt-4 rounded-lg border border-slate-800 bg-black/20 p-4 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <b className="text-emerald-200">{verdictCopy[result.verdict]}</b>
            <span className="text-slate-400">Fairness: {result.fairness_pct}%</span>
          </div>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <small className="text-slate-500">Side A total</small>
              <b className="block text-lg text-emerald-300">{result.side_a.total_value}</b>
            </div>
            <div>
              <small className="text-slate-500">Side B total</small>
              <b className="block text-lg text-emerald-300">{result.side_b.total_value}</b>
            </div>
          </div>
          <p className="mt-3 text-xs text-slate-500">{result.note}</p>
        </div>
      )}
    </section>
  );
}
