"use client";
import {useState} from 'react';
import type {PlayerDetail} from '@/lib/workspace-api.generated';
import {tradeCandidates, tradePackageOwner} from '@/lib/workspace';

export function WorkspaceTradePicker({label,players,ids,other,busy,onChange}: {
  label:string; players:PlayerDetail[]; ids:string[]; other:string[]; busy:boolean; onChange:(ids:string[])=>void;
}) {
  const [search,setSearch]=useState('');
  const [roster,setRoster]=useState('all');
  const owner=tradePackageOwner(players,ids);
  const opposite=tradePackageOwner(players,other);
  const teams=new Map<string,string>();
  for(const p of players) if(p.roster_id && ['your_roster','other_roster'].includes(p.ownership)) {
    teams.set(p.roster_id,`${p.roster_names.join(', ') || 'Unnamed roster'} · ${p.roster_id}`);
  }
  const matches=tradeCandidates(players,ids,other,search,owner ?? roster);
  return <section aria-label={`Side ${label} package`} className="min-w-0 rounded-xl border border-slate-700 bg-slate-950 p-4">
    <h4 className="font-semibold">Side {label} gives <span className="text-sm text-slate-400">{ids.length}/6 players</span></h4>
    {!!ids.length && !owner && <p role="alert" className="my-2 text-sm text-amber-200">Package ownership no longer matches this snapshot. Remove the affected players before continuing.</p>}
    <label className="mt-3 block text-sm">Side {label} team<select value={owner ?? roster} disabled={busy || !!ids.length} onChange={e=>{setRoster(e.target.value);setSearch('');}} className="mt-2 block min-h-11 w-full min-w-0 rounded border border-slate-600 bg-slate-900 p-2">
      <option value="all">Choose any eligible team</option>{[...teams].map(([id,name])=><option key={id} value={id} disabled={id===opposite}>{name}</option>)}
    </select></label>
    <p className="mt-2 text-xs text-slate-400">The first player binds this side to one team. Remove the package to change teams.</p>
    <ul aria-label={`Side ${label} selected players`} className="my-3 space-y-2">{ids.map(id=><li key={id} className="flex items-center justify-between gap-2 text-sm"><span>{players.find(p=>p.player_id===id)?.name ?? 'Player missing from snapshot'}</span><button disabled={busy} aria-label={`Remove ${players.find(p=>p.player_id===id)?.name ?? id} from side ${label}`} onClick={()=>onChange(ids.filter(p=>p!==id))} className="min-h-11 rounded border border-slate-600 px-3">Remove</button></li>)}</ul>
    <label className="block text-sm">Search side {label} players<input disabled={busy || ids.length>=6} value={search} onChange={e=>setSearch(e.target.value)} placeholder="Player, position, NFL team" className="mt-2 block min-h-11 w-full rounded border border-slate-600 bg-slate-900 p-2" /></label>
    <p role="status" className="my-2 text-xs text-slate-400">{ids.length>=6 ? 'Package full. Remove a player to add another.' : `${matches.length} eligible matches · showing ${Math.min(matches.length,12)}. Narrow by team or search.`}</p>
    {ids.length<6 && <ul aria-label={`Side ${label} search results`} className="divide-y divide-slate-800">{matches.slice(0,12).map(p=><li key={p.player_id} className="flex items-center justify-between gap-2 py-2"><div className="min-w-0 text-sm"><p>{p.name}</p><p className="text-xs text-slate-400">{p.position ?? '?'} · {p.team ?? '?'} · {p.roster_names.join(', ')}</p></div><button aria-label={`Add ${p.name} to side ${label}`} disabled={busy} onClick={()=>{onChange([...ids,p.player_id]);setSearch('');}} className="min-h-11 rounded border border-emerald-700 px-3 text-sm text-emerald-200">Add</button></li>)}</ul>}
  </section>;
}
