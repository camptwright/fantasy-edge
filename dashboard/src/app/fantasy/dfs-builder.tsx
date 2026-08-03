"use client";

import { useState } from "react";
import { apiPost, ApiError } from "@/lib/api";
import { Card, ErrorState } from "@/components/ui";

interface PoolPlayer {
  player_id: string;
  name: string;
  team: string;
  positions: string; // comma-separated in the UI, split before sending
  salary: number;
  projected_points: number;
  locked: boolean;
  excluded: boolean;
}

interface Assignment {
  slot_name: string;
  player_id: string;
  name: string;
  salary: number;
  projected_points: number;
}

interface OptimizeResult {
  feasible: boolean;
  total_salary: number;
  salary_cap: number;
  total_projected_points: number;
  assignments: Assignment[];
}

let nextId = 1;
function emptyPlayer(): PoolPlayer {
  return {
    player_id: `p${nextId++}`,
    name: "",
    team: "",
    positions: "",
    salary: 0,
    projected_points: 0,
    locked: false,
    excluded: false,
  };
}

export function DfsBuilder() {
  const [sport, setSport] = useState("nba");
  const [site, setSite] = useState("draftkings");
  const [pool, setPool] = useState<PoolPlayer[]>([emptyPlayer(), emptyPlayer()]);
  const [result, setResult] = useState<OptimizeResult | null>(null);
  const [optimizing, setOptimizing] = useState(false);
  const [optError, setOptError] = useState<string | null>(null);

  function updatePlayer(id: string, patch: Partial<PoolPlayer>) {
    setPool((prev) => prev.map((p) => (p.player_id === id ? { ...p, ...patch } : p)));
  }

  function removePlayer(id: string) {
    setPool((prev) => prev.filter((p) => p.player_id !== id));
  }

  async function optimize() {
    setOptimizing(true);
    setOptError(null);
    setResult(null);
    try {
      const players = pool
        .filter((p) => p.name && p.positions)
        .map((p) => ({
          player_id: p.player_id,
          name: p.name,
          team: p.team,
          positions: p.positions.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean),
          salary: p.salary,
          projected_points: p.projected_points,
        }));
      const locked_player_ids = pool.filter((p) => p.locked).map((p) => p.player_id);
      const excluded_player_ids = pool.filter((p) => p.excluded).map((p) => p.player_id);

      const res = await apiPost<OptimizeResult>("/fantasy/dfs/optimize", {
        sport,
        site,
        players,
        locked_player_ids,
        excluded_player_ids,
      });
      setResult(res);
    } catch (e) {
      setOptError(e instanceof ApiError ? e.message : "Optimization failed");
    } finally {
      setOptimizing(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <select
            value={sport}
            onChange={(e) => setSport(e.target.value)}
            className="rounded-md border border-border bg-bg px-2 py-1 text-sm"
          >
            <option value="nba">NBA</option>
            <option value="wnba">WNBA</option>
            <option value="nfl">NFL</option>
          </select>
          <select
            value={site}
            onChange={(e) => setSite(e.target.value)}
            className="rounded-md border border-border bg-bg px-2 py-1 text-sm"
          >
            <option value="draftkings">DraftKings</option>
            <option value="fanduel">FanDuel</option>
          </select>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-gray-500">
              <tr>
                <th className="px-2 py-1">Name</th>
                <th className="px-2 py-1">Team</th>
                <th className="px-2 py-1">Pos</th>
                <th className="px-2 py-1">Salary</th>
                <th className="px-2 py-1">Proj</th>
                <th className="px-2 py-1">Lock</th>
                <th className="px-2 py-1">Excl</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {pool.map((p) => (
                <tr key={p.player_id} className="border-t border-border">
                  <td className="px-2 py-1">
                    <input
                      value={p.name}
                      onChange={(e) => updatePlayer(p.player_id, { name: e.target.value })}
                      className="w-28 rounded border border-border bg-bg px-1 py-0.5"
                    />
                  </td>
                  <td className="px-2 py-1">
                    <input
                      value={p.team}
                      onChange={(e) => updatePlayer(p.player_id, { team: e.target.value })}
                      className="w-16 rounded border border-border bg-bg px-1 py-0.5"
                    />
                  </td>
                  <td className="px-2 py-1">
                    <input
                      value={p.positions}
                      onChange={(e) => updatePlayer(p.player_id, { positions: e.target.value })}
                      placeholder="PG,SG"
                      className="w-20 rounded border border-border bg-bg px-1 py-0.5 placeholder:text-gray-600"
                    />
                  </td>
                  <td className="px-2 py-1">
                    <input
                      type="number"
                      value={p.salary}
                      onChange={(e) => updatePlayer(p.player_id, { salary: Number(e.target.value) })}
                      className="w-20 rounded border border-border bg-bg px-1 py-0.5"
                    />
                  </td>
                  <td className="px-2 py-1">
                    <input
                      type="number"
                      value={p.projected_points}
                      onChange={(e) =>
                        updatePlayer(p.player_id, { projected_points: Number(e.target.value) })
                      }
                      className="w-16 rounded border border-border bg-bg px-1 py-0.5"
                    />
                  </td>
                  <td className="px-2 py-1 text-center">
                    <input
                      type="checkbox"
                      checked={p.locked}
                      onChange={(e) => updatePlayer(p.player_id, { locked: e.target.checked })}
                    />
                  </td>
                  <td className="px-2 py-1 text-center">
                    <input
                      type="checkbox"
                      checked={p.excluded}
                      onChange={(e) => updatePlayer(p.player_id, { excluded: e.target.checked })}
                    />
                  </td>
                  <td className="px-2 py-1">
                    <button
                      onClick={() => removePlayer(p.player_id)}
                      className="text-xs text-gray-500 hover:text-red-400"
                    >
                      remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => setPool((prev) => [...prev, emptyPlayer()])}
            className="rounded-md border border-border px-3 py-1.5 text-sm text-gray-300 hover:bg-white/5"
          >
            + Add player
          </button>
          <button
            onClick={optimize}
            disabled={optimizing}
            className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-black disabled:opacity-50"
          >
            {optimizing ? "Optimizing…" : "Optimize Lineup"}
          </button>
        </div>
        {optError && <ErrorState message={optError} />}
      </Card>

      {result && (
        <Card className="space-y-2">
          <div className="flex justify-between text-sm">
            <span>
              Salary: <span className="font-mono">${result.total_salary}</span> / $
              {result.salary_cap}
            </span>
            <span>
              Projected:{" "}
              <span className="font-semibold text-accent">
                {result.total_projected_points.toFixed(1)} pts
              </span>
            </span>
          </div>
          <table className="w-full text-sm">
            <tbody>
              {result.assignments.map((a) => (
                <tr key={a.slot_name} className="border-t border-border">
                  <td className="px-2 py-1 text-xs uppercase text-gray-500">{a.slot_name}</td>
                  <td className="px-2 py-1">{a.name}</td>
                  <td className="px-2 py-1 font-mono">${a.salary}</td>
                  <td className="px-2 py-1 font-mono">{a.projected_points.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
