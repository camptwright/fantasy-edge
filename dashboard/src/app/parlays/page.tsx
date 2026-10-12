"use client";
import {useState} from 'react';
type Result={status:string;note:string;legs:{id:string;selection:string;price_american:number;model_probability:number}[];combined_probability?:number;combined_price_american?:number;ai_used?:boolean};
export default function ParlayAssistant(){
 const [result,setResult]=useState<Result|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 return <main className="mx-auto max-w-4xl space-y-5 px-4 py-6 md:px-8"><header><p className="text-xs font-medium uppercase tracking-wider text-slate-400">Markets</p><h1 className="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">Parlay research</h1></header>
 <p className="text-sm text-slate-400">AI selects from current eligible offers. It cannot invent picks or override validation. Same-game combinations are unsupported. No wagers are placed.</p>
 <form className="flex flex-wrap items-end gap-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm" onSubmit={async e=>{
  e.preventDefault();const form=new FormData(e.currentTarget);setBusy(true);setError('');setResult(null);
  try{const response=await fetch('/api/parlays/assist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sport:form.get('sport'),book:form.get('book'),leg_count:Number(form.get('legs')),preferences:form.get('preferences')}),signal:AbortSignal.timeout(35000)});
   const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Unable to construct this request');setResult(data);
  }catch(err){setError(err instanceof Error?err.message:'Assistant unavailable');}finally{setBusy(false);}
 }}>
 <label>Sport<select name="sport" className="mt-1 block min-h-11 rounded-lg border border-slate-700 bg-slate-950 px-3">{['nfl','ncaaf','nba','mlb','nhl'].map(s=><option key={s} value={s}>{s.toUpperCase()}</option>)}</select></label>
 <label>Book<select name="book" className="mt-1 block min-h-11 rounded-lg border border-slate-700 bg-slate-950 px-3">{['draftkings','betmgm','caesars','fanduel'].map(b=><option key={b}>{b}</option>)}</select></label>
 <label>Legs<select name="legs" className="mt-1 block min-h-11 rounded-lg border border-slate-700 bg-slate-950 px-3">{[2,3,4].map(n=><option key={n}>{n}</option>)}</select></label>
 <label className="w-full">Preferences<textarea name="preferences" maxLength={500} placeholder="For example: prefer player props" className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-950 p-3"/></label>
 <button disabled={busy} className="min-h-11 rounded-lg bg-emerald-500 px-4 font-semibold text-slate-950 hover:bg-emerald-400 disabled:bg-slate-800 disabled:text-slate-500">{busy?'Checking offers and requesting AI selection…':'Build research parlay'}</button></form>
 {error&&<p role="alert" className="text-amber-300">{error}</p>}
 {result&&<section aria-live="polite" className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-4 text-sm"><h2 className="font-semibold capitalize">{result.status.replaceAll('_',' ')}</h2><p>{result.note}</p>
 {result.legs.map((leg,i)=><p key={`${leg.id}:${i}`}>{leg.selection} · individual price {leg.price_american} · model probability {(leg.model_probability*100).toFixed(1)}%</p>)}
 {result.combined_probability!=null&&<p>Independence estimate: {(result.combined_probability*100).toFixed(1)}% · theoretical combined American odds: {result.combined_price_american}. Not a verified payout or demonstrated profitable strategy.</p>}
 </section>}</main>;
}
