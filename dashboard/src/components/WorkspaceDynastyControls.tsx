"use client";
import { useState } from "react";
export type DynastyPick = {side:'a'|'b';season:number;round:number;slot?:number;value?:number;source?:string;original_roster_id?:string;pick_id?:string};
export type DynastyScenario = {goal:'balanced'|'contender'|'rebuild';picks:DynastyPick[]};
export type PickOffer = {id:string;season:number;round:number;original_roster_id:number;owner_roster_id:number;value:number|null;basis:string};
type Inventory = {status:string;picks:PickOffer[];market_captured_at?:string|null;note?:string|null};
const ORDINAL = ['','1st','2nd','3rd','4th','5th','6th','7th'];
const BASIS: Record<string,string> = {early_round_estimated_from_current_standings:'early (standings estimate)',mid_round_estimated_from_current_standings:'mid (standings estimate)',
  late_round_estimated_from_current_standings:'late (standings estimate)',generic_round:'round average',not_priced_by_market:'not priced'};

/** "2027 1st · from Team X · 3,287" — the label for one verified pick. */
export function pickLabel(p:PickOffer, names:Record<string,string>, own:string|null): string {
  const from = String(p.original_roster_id) === own ? 'own' : `via ${names[String(p.original_roster_id)] ?? `roster ${p.original_roster_id}`}`;
  return `${p.season} ${ORDINAL[p.round] ?? `R${p.round}`} (${from}) · ${p.value == null ? 'unpriced' : p.value.toLocaleString()} · ${BASIS[p.basis] ?? p.basis}`;
}

export function WorkspaceDynastyControls({value,onChange,disabled=false,season,leagueId,owners={a:null,b:null},rosterNames={}}:{value:DynastyScenario;onChange:(value:DynastyScenario)=>void;disabled?:boolean;season:number;leagueId?:string;owners?:{a:string|null;b:string|null};rosterNames?:Record<string,string>}) {
  const [inventory,setInventory]=useState<Inventory|null>(null);
  const [loadError,setLoadError]=useState<string|null>(null);
  function update(index:number,change:Partial<DynastyPick>) {onChange({...value,picks:value.picks.map((p,i)=>i===index?{...p,...change}:p)});}
  async function load() {
    if (inventory||!leagueId) return;
    try {
      const response=await fetch(`/api/workspace/draft-picks?${new URLSearchParams({league:leagueId})}`,{signal:AbortSignal.timeout(6000)});
      const body=await response.json();
      if (!response.ok) {setLoadError(typeof body.detail==='string'?body.detail:'Draft picks unavailable');return;}
      setInventory(body);
    } catch {setLoadError('Draft picks unavailable');}
  }
  function toggle(side:'a'|'b',p:PickOffer) {
    const chosen=value.picks.some(x=>x.pick_id===p.id);
    onChange({...value,picks:chosen?value.picks.filter(x=>x.pick_id!==p.id):[...value.picks,{side,pick_id:p.id,season:p.season,round:p.round}]});
  }
  const input='min-h-11 rounded-lg border border-slate-700 bg-slate-950 px-2 text-sm';
  const typed=value.picks.map((p,i)=>({p,i})).filter(({p})=>!p.pick_id);
  return <details className="mt-4 rounded-xl border border-slate-800 p-4" onToggle={e=>{if((e.target as HTMLDetailsElement).open)load();}}><summary className="cursor-pointer font-medium">Dynasty goals and rookie picks</summary>
    <fieldset disabled={disabled} className="mt-3 space-y-3"><label className="flex flex-wrap items-center gap-3 text-sm">Your goal <select aria-label="Dynasty planning goal" className={input} value={value.goal} onChange={e=>onChange({...value,goal:e.target.value as DynastyScenario['goal']})}><option value="balanced">Balanced</option><option value="contender">Contend now</option><option value="rebuild">Rebuild</option></select></label>
    {loadError && <p className="text-xs text-amber-200">{loadError}</p>}
    {inventory && inventory.status!=='observed' && inventory.status!=='ownership_only' && <p className="text-xs text-slate-400">No verified pick inventory ({inventory.status.replaceAll('_',' ')}). You can still type a scenario pick below.</p>}
    {inventory?.picks.length ? (['a','b'] as const).map(side=>{const owner=owners[side];const mine=inventory.picks.filter(p=>String(p.owner_roster_id)===owner);
      return <div key={side}><p className="text-xs font-medium text-slate-300">Side {side.toUpperCase()} can include {owner?`(${rosterNames[owner]??`roster ${owner}`})`:''}</p>
        {!owner ? <p className="text-xs text-slate-500">Choose this side&apos;s players first.</p> : !mine.length ? <p className="text-xs text-slate-500">This team owns no picks in the next three drafts.</p> :
        <div className="mt-1 flex flex-wrap gap-2">{mine.map(p=>{const on=value.picks.some(x=>x.pick_id===p.id);
          return <button type="button" key={p.id} aria-pressed={on} onClick={()=>toggle(side,p)} className={`${input} ${on?'border-sky-500 bg-sky-500/15':''}`}>{pickLabel(p,rosterNames,owner)}</button>;})}</div>}</div>;}) : null}
    {inventory?.note && <p className="text-xs text-slate-500">{inventory.note}{inventory.market_captured_at?` Prices captured ${new Date(inventory.market_captured_at).toLocaleDateString()}.`:''}</p>}
    <p className="text-xs text-slate-400">Typed picks are for leagues or picks the inventory does not cover. Enter values only in FantasyCalc market-index units; unpriced picks stay unpriced.</p>
    {typed.map(({p,i})=><div key={i} className="flex flex-wrap gap-2 rounded-lg bg-slate-950/60 p-3">
      <label className="text-xs">Giving side <select className={`block ${input}`} value={p.side} onChange={e=>update(i,{side:e.target.value as 'a'|'b'})}><option value="a">A</option><option value="b">B</option></select></label>
      <label className="text-xs">Season <input className={`block w-24 ${input}`} type="number" min={season} max={2100} value={p.season} onChange={e=>update(i,{season:Number(e.target.value)})}/></label>
      <label className="text-xs">Round <input className={`block w-20 ${input}`} type="number" min={1} max={10} value={p.round} onChange={e=>update(i,{round:Number(e.target.value)})}/></label>
      <label className="text-xs">Pick slot (optional) <input className={`block w-28 ${input}`} type="number" min={1} max={32} value={p.slot??''} onChange={e=>update(i,{slot:e.target.value===''?undefined:Number(e.target.value)})}/></label>
      <label className="text-xs">Index value (optional) <input className={`block w-32 ${input}`} type="number" min={0} value={p.value??''} onChange={e=>update(i,{value:e.target.value===''?undefined:Number(e.target.value)})}/></label>
      <label className="text-xs">Price source <input className={`block w-40 ${input}`} maxLength={200} value={p.source??''} placeholder="Your scenario or source" onChange={e=>update(i,{source:e.target.value})}/></label>
      <button type="button" className={input} onClick={()=>onChange({...value,picks:value.picks.filter((_,j)=>j!==i)})}>Remove pick</button>
    </div>)}
    <button type="button" disabled={value.picks.length>=12} className={input} onClick={()=>onChange({...value,picks:[...value.picks,{side:'a',season:season+1,round:1}]})}>Add typed scenario pick</button>
    </fieldset>
  </details>;
}
