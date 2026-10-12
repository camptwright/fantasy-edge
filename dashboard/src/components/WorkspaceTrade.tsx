"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { tradeBlockerText, tradePackageOwner, type ResearchContext } from "@/lib/workspace";
import { WorkspaceTradePicker } from "@/components/WorkspaceTradePicker";
import type { TradeResult } from "@/lib/workspace-api.generated";
import { SnapshotWindow } from "@/components/SnapshotWindow";
import { WorkspaceTradeOutlook } from "@/components/WorkspaceTradeOutlook";

export function WorkspaceTrade({ overview }: { overview: ResearchContext }) {
  const router = useRouter();
  const [refreshing, startRefresh] = useTransition();
  const generation = useRef(overview.generated_at);
  generation.current = overview.generated_at;
  const [a, setA] = useState<string[]>([]);
  const [b, setB] = useState<string[]>([]);
  const emptyPlans = {a:{add:[] as string[],drop:[] as string[]}, b:{add:[] as string[],drop:[] as string[]}};
  const [plans, setPlans] = useState(emptyPlans);
  const [busy, setBusy] = useState(false);
  const [adjustmentsOpen, setAdjustmentsOpen] = useState(false);
  const [result, setResult] = useState<TradeResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const players = overview.comparison_players;
  const ownerA = tradePackageOwner(players, a), ownerB = tradePackageOwner(players, b);
  useEffect(() => { setResult(null); setError(null); setBusy(false); }, [overview.generated_at]);
  async function evaluate() {
    const requestedGeneration = overview.generated_at;
    setBusy(true); setResult(null); setError(null);
    try {
      const response = await fetch('/api/workspace/trade', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ league_id: overview.league_id, generated_at: overview.generated_at, side_a: a, side_b: b, ...plans }),
        signal: AbortSignal.timeout(10000) });
      const body = await response.json();
      if (generation.current !== requestedGeneration) return;
      if (!response.ok) { setError(typeof body.detail === 'string' ? body.detail : 'Invalid or unavailable comparison'); return; }
      setResult(body);
    } catch { if (generation.current === requestedGeneration) setError('Trade preview unavailable. Refresh and retry.'); }
    finally { if (generation.current === requestedGeneration) setBusy(false); }
  }
  return <section aria-label="Trade package preview" className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h3 className="text-lg font-semibold">Build a trade <span className="ml-1 rounded bg-sky-500/15 px-2 py-0.5 align-middle text-[11px] font-medium uppercase tracking-wider text-sky-300">Lineup-impact research</span></h3>
      <button disabled={busy || refreshing} onClick={() => {setResult(null);setError(null);startRefresh(() => router.refresh());}} className="min-h-11 rounded-lg border border-slate-700 px-3 text-sm hover:border-slate-500">{refreshing ? 'Refreshing evidence…' : 'Refresh trade evidence'}</button>
    </div>
    <p className="mt-2 text-xs text-slate-400">Refresh clears the previous result. Selections stay while this panel remains open; review ownership and locks again before evaluating. An expired or unavailable checkpoint hides this panel and may clear the draft.</p>
    <p className="my-3 text-sm text-slate-300">Choose what each team gives. Each package must belong to one of two distinct rosters. Up to six players per side. For uneven trades, explicitly balance each roster with add/drop plans below. Unrostered players are not guaranteed claimable; no waiver timing or platform eligibility is inferred.</p>
    <div className="grid gap-4 md:grid-cols-2">{[{label:'A', ids:a, other:b, set:setA}, {label:'B', ids:b, other:a, set:setB}].map(side => <WorkspaceTradePicker key={side.label} label={side.label} ids={side.ids} other={side.other} players={players} busy={busy || refreshing} onChange={ids=>{side.set(ids);setPlans(emptyPlans);setResult(null);setError(null);}} />)}</div>
    <details onToggle={e=>setAdjustmentsOpen(e.currentTarget.open)} className="mt-4"><summary className="min-h-11 cursor-pointer text-emerald-200">Uneven-trade add/drop plans</summary>
      <p className="mb-3 text-xs text-slate-400">Changing either trade package clears both plans. Only unlocked adjustment players with known ownership are listed. Empty options may mean no eligible players in this checkpoint.</p>
      {adjustmentsOpen && <div className="grid gap-4 md:grid-cols-2">{(['a','b'] as const).map(side => {
        const give = side === 'a' ? a : b, receive = side === 'a' ? b : a;
        const owners = give.map(id => players.find(p => p.player_id === id)?.roster_id);
        const owner = owners.length && owners[0] && owners.every(id => id === owners[0]) ? owners[0] : null;
        const delta = receive.length - give.length + plans[side].add.length - plans[side].drop.length;
        return <div key={side}><h4>Side {side.toUpperCase()} · net roster change {delta > 0 ? '+' : ''}{delta}</h4>
          {!owner && <p className="text-xs text-amber-200">Select a package belonging to one roster first.</p>}
          {(['add','drop'] as const).map(kind => <div key={kind} className="mt-2"><label className="text-sm">Side {side.toUpperCase()} {kind}<select value="" disabled={busy || !owner || plans[side][kind].length >= 6} onChange={e => {if(e.target.value){setPlans({...plans,[side]:{...plans[side],[kind]:[...plans[side][kind],e.target.value]}});setResult(null);setError(null);}}} className="mt-1 block min-h-11 w-full rounded border border-slate-600 bg-slate-950 p-2">
            <option value="">Choose adjustment player</option>{players.filter(p => !p.locked && ![...a,...b,...plans.a.add,...plans.a.drop,...plans.b.add,...plans.b.drop].includes(p.player_id) && (kind === 'add' ? p.ownership === 'unrostered_snapshot' : p.roster_id === owner)).map(p => <option key={p.player_id} value={p.player_id}>{p.name} · {p.position}</option>)}
          </select></label>{plans[side][kind].map(id => <button key={id} disabled={busy} className="mt-2 min-h-11 rounded border border-slate-600 px-2 text-sm" onClick={() => {setPlans({...plans,[side]:{...plans[side],[kind]:plans[side][kind].filter(pid => pid !== id)}});setResult(null);setError(null);}}>Remove {players.find(p => p.player_id === id)?.name} from {side.toUpperCase()} {kind}</button>)}</div>)}
        </div>;
      })}</div>}
    </details>
    <button disabled={busy || refreshing || !ownerA || !ownerB || ownerA === ownerB} onClick={evaluate} className="mt-4 min-h-11 w-full rounded-lg bg-emerald-500 px-4 font-semibold text-slate-950 hover:bg-emerald-400 disabled:bg-slate-800 disabled:text-slate-500 sm:w-auto">{busy ? 'Checking saved evidence…' : 'Evaluate saved roster impact'}</button>
    {error && <p role="alert" className="mt-3 text-amber-200">{error}</p>}
    {result && <SnapshotWindow expiresAt={result.expires_at}><div role="status" className="mt-6 space-y-2 text-sm">
      {result.outlook && <WorkspaceTradeOutlook outlook={result.outlook} a={a} b={b} players={players} />}
      <h4 className="pt-4 font-semibold">History-based check <span className="text-xs font-normal text-slate-500">· {result.status.replaceAll('_',' ')}</span></h4>
      {result.blockers.map(reason => <p key={reason} className="text-amber-200">{tradeBlockerText(reason)}</p>)}
      {[result.side_a,result.side_b].map((side,i) => side && <p key={`size-${i}`}>{side.team} roster size: {side.roster_size_before ?? 'unknown'} → {side.roster_size_after ?? 'unknown'}</p>)}
      {[result.side_a,result.side_b].map((side,i) => side && (side.missing_players.length > 0 || side.availability_review_players.length > 0) && <details key={`evidence-${i}`} className="rounded border border-slate-700 p-3"><summary className="cursor-pointer text-emerald-200">{side.team}: players needing review</summary>
        {!!side.missing_players.length && <p className="mt-2">Incomplete valuation evidence: {side.missing_players.join(', ')}.</p>}
        {!!side.availability_review_players.length && <p className="mt-2">Availability review: {side.availability_review_players.join(', ')}.</p>}
        <p className="mt-2 text-xs text-slate-400">These can include supporting bench players, not just the traded package. Review player evidence; do not interpret a withheld gain as zero.</p>
      </details>)}
      {result.status === 'research_candidate' && [result.side_a, result.side_b].map((side, i) => <p key={i}>{side?.team}: {side?.conditional_lineup_gain == null ? 'Unknown' : side.conditional_lineup_gain.toFixed(2)} conditional offensive lineup points/game change</p>)}
      <p className="text-slate-400">{result.note} No trade is submitted.</p>
    </div></SnapshotWindow>}
  </section>;
}
