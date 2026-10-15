"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { pts, type Overview } from "@/lib/workspace";

type Participant = { player_id: string; name: string; role: string; prediction: number; ros_points?: number | null };
type Outcome = { player_id: string; status: string; actual: number | null; error: number | null };
type Record = { id: string; action: string; week: number; captured_at: string; note: string;
  participants: Participant[]; outcomes: Outcome[] };

export function WorkspaceDecisionHistory({overview}: {overview: Overview}) {
  const [records, setRecords] = useState<Record[]>([]);
  const [action, setAction] = useState<"start"|"pickup"|"trade">("start");
  const [selected, setSelected] = useState("");
  const [other, setOther] = useState("");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<{signature: string; id: string} | null>(null);
  const load = useCallback(async () => {
    try {
      const response = await fetch(`/api/workspace/decisions?league=${encodeURIComponent(overview.league_id)}`, {cache: "no-store"});
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "History unavailable");
      setRecords(body.records ?? []);
    } catch (error) { setMessage(error instanceof Error ? error.message : "History unavailable"); }
  }, [overview.league_id]);
  useEffect(() => { setRecords([]); void load(); }, [load]);
  const roster = overview.roster_players.filter(p => !p.reserve_slot);
  const catalog = [...new Map([...overview.comparison_players, ...overview.engine_waivers.rows.map(r => r.add)]
    .map(p => [p.player_id, p])).values()];
  const options = action === "pickup" ? catalog.filter(p => p.ownership === "unrostered_snapshot")
    : catalog.filter(p => p.ownership === "other_roster");
  const starters = overview.matchup.mine?.starters ?? [];
  const lineup = starters.flatMap(s => s.player_id ? [s.player_id] : []);
  const lineupReady = !!lineup.length && lineup.length === starters.length && lineup.every(id => roster.some(p => p.player_id === id && !p.locked));
  async function save() {
    const body = {league_id: overview.league_id, generated_at: overview.generated_at, action,
      player_ids: action === "start" ? lineup : action === "pickup" ? [other, selected] : [selected],
      counterparty_player_ids: action === "trade" ? [other] : [], note};
    const signature = JSON.stringify(body);
    if (!pending.current || pending.current.signature !== signature) pending.current = {signature, id: crypto.randomUUID()};
    setBusy(true); setMessage("");
    try {
      const response = await fetch("/api/workspace/decisions", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...body, request_id: pending.current.id})});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? "Save unavailable");
      pending.current = null; setMessage("Decision saved with this snapshot’s expectations."); setNote("");
      await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Save unavailable"); }
    finally { setBusy(false); }
  }
  return <div className="space-y-6">
    <section className="rounded-2xl border border-slate-800 p-5" aria-label="Save personal decision">
      <h2 className="text-lg font-semibold">Your decision journal</h2>
      <p className="mt-2 text-sm text-slate-400">Save the choice you intend to make, its projections, and your reasoning. Results appear after final scores are available.</p>
      <fieldset disabled={busy} className="mt-4 space-y-3">
        <label className="block text-sm">Decision<select value={action} onChange={e => {setAction(e.target.value as typeof action); setSelected(""); setOther("");}}
          className="mt-1 min-h-11 w-full rounded-lg border border-slate-700 bg-slate-950 px-3">
          <option value="start">Save current starting lineup</option><option value="pickup">Pickup and drop</option><option value="trade">Trade one player for one player</option>
        </select></label>
        {action !== "start" && <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm">{action === "pickup" ? "Drop from your roster" : "Give from your roster"}<select value={selected} onChange={e => setSelected(e.target.value)} className="mt-1 min-h-11 w-full rounded-lg border border-slate-700 bg-slate-950 px-3"><option value="">Choose player</option>{roster.map(p => <option key={p.player_id} value={p.player_id}>{p.name}</option>)}</select></label>
          <label className="text-sm">{action === "pickup" ? "Add available player" : "Receive from another roster"}<select value={other} onChange={e => setOther(e.target.value)} className="mt-1 min-h-11 w-full rounded-lg border border-slate-700 bg-slate-950 px-3"><option value="">Choose player</option>{options.map(p => <option key={p.player_id} value={p.player_id}>{p.name}</option>)}</select></label>
        </div>}
        <label className="block text-sm">Reason or note<textarea value={note} maxLength={1000} onChange={e => setNote(e.target.value)} className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-950 p-3" rows={2} placeholder="What made you choose this?" /></label>
        <button type="button" disabled={busy || (action === "start" ? !lineupReady : !selected || !other)} onClick={() => void save()} className="min-h-11 rounded-lg bg-emerald-500 px-4 font-semibold text-slate-950 disabled:opacity-40">{busy ? "Saving…" : "Save decision"}</button>
        {action === "start" && !lineupReady && <p className="text-xs text-slate-400">A complete unlocked pregame lineup is required. Save before the first player starts.</p>}
      </fieldset>
      <p className="mt-3 text-xs text-slate-500">This records your plan; submit roster changes on your fantasy platform. Pickup and trade outcomes describe the players’ scores, rather than proving the transaction caused a gain.</p>
      {message && <p role="status" className="mt-3 text-sm text-amber-200">{message}</p>}
    </section>
    <section className="rounded-2xl border border-slate-800 p-5" aria-label="Personal decision history">
      <div className="flex justify-between gap-3"><h2 className="font-semibold">Saved decisions</h2><button type="button" onClick={() => void load()} className="text-xs text-slate-400 underline">Refresh results</button></div>
      {!records.length && <p className="mt-3 text-sm text-slate-400">No saved decisions for this league yet.</p>}
      <ul className="mt-3 divide-y divide-slate-800">{records.map(record => <li key={record.id} className="py-4">
        <p className="font-medium">Week {record.week} · {record.action === "start" ? "Starting lineup" : record.action === "pickup" ? "Pickup" : "Trade"}</p>
        <p className="mt-1 text-xs text-slate-500">Saved {new Date(record.captured_at).toLocaleString("en-US", {timeZone: "America/Chicago"})}</p>
        {record.note && <p className="mt-2 text-sm text-slate-300">{record.note}</p>}
        <ul className="mt-2 space-y-1 text-sm">{record.participants.map(p => {const result = record.outcomes.find(r => r.player_id === p.player_id);
          return <li key={p.player_id}>{p.name} <span className="text-slate-500">({p.role})</span> · expected {pts(p.prediction)} · {result?.status === "graded" ? <>actual {pts(result.actual)} · difference {pts(result.error)}</> : <span className="text-slate-500">{result?.status.replaceAll("_", " ") ?? "awaiting final"}</span>}</li>;})}</ul>
      </li>)}</ul>
    </section>
  </div>;
}
