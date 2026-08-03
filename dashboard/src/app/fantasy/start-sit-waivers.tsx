"use client";

import { useState } from "react";
import { apiPost, ApiError } from "@/lib/api";
import { Card, ErrorState } from "@/components/ui";

interface RosterPlayer {
  player_id: string;
  name: string;
  position: string;
  projected_points: number;
  rostered: boolean;
}

interface VorRow {
  player_id: string;
  name: string;
  position: string;
  projected_points: number;
  vor: number;
  position_rank: number;
}

let nextId = 1;
function emptyPlayer(): RosterPlayer {
  return { player_id: `v${nextId++}`, name: "", position: "", projected_points: 0, rostered: true };
}

function RosterTable({
  players,
  onChange,
  onAdd,
  onRemove,
  showRostered,
}: {
  players: RosterPlayer[];
  onChange: (id: string, patch: Partial<RosterPlayer>) => void;
  onAdd: () => void;
  onRemove: (id: string) => void;
  showRostered: boolean;
}) {
  return (
    <div className="space-y-2">
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase text-gray-500">
          <tr>
            <th className="px-2 py-1">Name</th>
            <th className="px-2 py-1">Position</th>
            <th className="px-2 py-1">Proj pts</th>
            {showRostered && <th className="px-2 py-1">Rostered</th>}
            <th />
          </tr>
        </thead>
        <tbody>
          {players.map((p) => (
            <tr key={p.player_id} className="border-t border-border">
              <td className="px-2 py-1">
                <input
                  value={p.name}
                  onChange={(e) => onChange(p.player_id, { name: e.target.value })}
                  className="w-28 rounded border border-border bg-bg px-1 py-0.5"
                />
              </td>
              <td className="px-2 py-1">
                <input
                  value={p.position}
                  onChange={(e) => onChange(p.player_id, { position: e.target.value.toUpperCase() })}
                  className="w-16 rounded border border-border bg-bg px-1 py-0.5"
                />
              </td>
              <td className="px-2 py-1">
                <input
                  type="number"
                  value={p.projected_points}
                  onChange={(e) =>
                    onChange(p.player_id, { projected_points: Number(e.target.value) })
                  }
                  className="w-20 rounded border border-border bg-bg px-1 py-0.5"
                />
              </td>
              {showRostered && (
                <td className="px-2 py-1 text-center">
                  <input
                    type="checkbox"
                    checked={p.rostered}
                    onChange={(e) => onChange(p.player_id, { rostered: e.target.checked })}
                  />
                </td>
              )}
              <td className="px-2 py-1">
                <button
                  onClick={() => onRemove(p.player_id)}
                  className="text-xs text-gray-500 hover:text-red-400"
                >
                  remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        onClick={onAdd}
        className="rounded-md border border-border px-3 py-1.5 text-sm text-gray-300 hover:bg-white/5"
      >
        + Add player
      </button>
    </div>
  );
}

export function StartSitView() {
  const [players, setPlayers] = useState<RosterPlayer[]>([emptyPlayer(), emptyPlayer()]);
  const [starters, setStarters] = useState("RB:2,WR:2,TE:1");
  const [result, setResult] = useState<{ start: VorRow[]; sit: VorRow[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function update(id: string, patch: Partial<RosterPlayer>) {
    setPlayers((prev) => prev.map((p) => (p.player_id === id ? { ...p, ...patch } : p)));
  }

  async function evaluate() {
    setLoading(true);
    setErr(null);
    try {
      const starters_by_position: Record<string, number> = {};
      for (const part of starters.split(",")) {
        const [pos, count] = part.split(":").map((s) => s.trim());
        if (pos && count) starters_by_position[pos.toUpperCase()] = Number(count);
      }
      const roster = players
        .filter((p) => p.name && p.position)
        .map(({ player_id, name, position, projected_points }) => ({
          player_id,
          name,
          position,
          projected_points,
        }));
      const res = await apiPost<{ start: VorRow[]; sit: VorRow[] }>("/fantasy/start-sit", {
        roster,
        starters_by_position,
      });
      setResult(res);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Evaluation failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <p className="text-sm text-gray-400">
          Ranks your roster by value over replacement, not just raw projected points -
          scarcity at a position matters as much as talent.
        </p>
        <RosterTable
          players={players}
          onChange={update}
          onAdd={() => setPlayers((prev) => [...prev, emptyPlayer()])}
          onRemove={(id) => setPlayers((prev) => prev.filter((p) => p.player_id !== id))}
          showRostered={false}
        />
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-400">Starting slots (POS:count):</label>
          <input
            value={starters}
            onChange={(e) => setStarters(e.target.value)}
            className="w-56 rounded border border-border bg-bg px-2 py-1 text-sm"
          />
        </div>
        <button
          onClick={evaluate}
          disabled={loading}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-black disabled:opacity-50"
        >
          {loading ? "Evaluating…" : "Evaluate"}
        </button>
        {err && <ErrorState message={err} />}
      </Card>

      {result && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Card>
            <h3 className="mb-2 text-sm font-semibold text-accent">Start</h3>
            {result.start.map((r) => (
              <div key={r.player_id} className="flex justify-between border-t border-border py-1 text-sm">
                <span>{r.name} ({r.position})</span>
                <span className="font-mono">VOR {r.vor.toFixed(1)}</span>
              </div>
            ))}
          </Card>
          <Card>
            <h3 className="mb-2 text-sm font-semibold text-gray-400">Sit</h3>
            {result.sit.map((r) => (
              <div key={r.player_id} className="flex justify-between border-t border-border py-1 text-sm">
                <span>{r.name} ({r.position})</span>
                <span className="font-mono">VOR {r.vor.toFixed(1)}</span>
              </div>
            ))}
          </Card>
        </div>
      )}
    </div>
  );
}

export function WaiversView() {
  const [players, setPlayers] = useState<RosterPlayer[]>([emptyPlayer(), emptyPlayer()]);
  const [result, setResult] = useState<VorRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function update(id: string, patch: Partial<RosterPlayer>) {
    setPlayers((prev) => prev.map((p) => (p.player_id === id ? { ...p, ...patch } : p)));
  }

  async function findTargets() {
    setLoading(true);
    setErr(null);
    try {
      const available_players = players
        .filter((p) => p.name && p.position)
        .map(({ player_id, name, position, projected_points }) => ({
          player_id,
          name,
          position,
          projected_points,
        }));
      const rostered_player_ids = players.filter((p) => p.rostered).map((p) => p.player_id);
      const res = await apiPost<VorRow[]>("/fantasy/waivers", {
        available_players,
        rostered_player_ids,
        limit: 20,
      });
      setResult(res);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Lookup failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card className="space-y-3">
        <p className="text-sm text-gray-400">
          Checking &quot;Rostered&quot; excludes a player from the waiver-target list even
          though they&apos;re included in the VOR ranking pool - a rostered star still
          anchors the position&apos;s replacement level.
        </p>
        <RosterTable
          players={players}
          onChange={update}
          onAdd={() => setPlayers((prev) => [...prev, emptyPlayer()])}
          onRemove={(id) => setPlayers((prev) => prev.filter((p) => p.player_id !== id))}
          showRostered={true}
        />
        <button
          onClick={findTargets}
          disabled={loading}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-black disabled:opacity-50"
        >
          {loading ? "Searching…" : "Find Waiver Targets"}
        </button>
        {err && <ErrorState message={err} />}
      </Card>

      {result && (
        <Card>
          {result.map((r) => (
            <div key={r.player_id} className="flex justify-between border-t border-border py-1 text-sm first:border-t-0">
              <span>{r.name} ({r.position})</span>
              <span className="font-mono">VOR {r.vor.toFixed(1)}</span>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
