"use client";
import {useState} from 'react';
type Result={status:string;note:string;legs:{id:string;selection:string;price_american:number;model_probability:number}[];combined_probability?:number;combined_price_american?:number;ai_used?:boolean};
export default function ParlayAssistant(){
 const [result,setResult]=useState<Result|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 return <main className="mx-auto max-w-4xl space-y-5 p-6"><h1 className="text-3xl font-semibold">AI-assisted parlay research</h1>
 <p>AI selects from current eligible offers. It cannot invent picks or override validation. Same-game combinations are unsupported. No wagers are placed.</p>
 <form className="flex flex-wrap items-end gap-4" onSubmit={async e=>{
  e.preventDefault();const form=new FormData(e.currentTarget);setBusy(true);setError('');setResult(null);
  try{const response=await fetch('/api/parlays/assist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sport:form.get('sport'),book:form.get('book'),leg_count:Number(form.get('legs')),preferences:form.get('preferences')}),signal:AbortSignal.timeout(35000)});
   const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Unable to construct this request');setResult(data);
  }catch(err){setError(err instanceof Error?err.message:'Assistant unavailable');}finally{setBusy(false);}
 }}>
 <label>Sport<select name="sport" className="block rounded bg-slate-800 p-2">{['nfl','ncaaf','nba','mlb','nhl'].map(s=><option key={s} value={s}>{s.toUpperCase()}</option>)}</select></label>
 <label>Book<select name="book" className="block rounded bg-slate-800 p-2">{['draftkings','betmgm','caesars','fanduel'].map(b=><option key={b}>{b}</option>)}</select></label>
 <label>Legs<select name="legs" className="block rounded bg-slate-800 p-2">{[2,3,4].map(n=><option key={n}>{n}</option>)}</select></label>
 <label className="w-full">Preferences<textarea name="preferences" maxLength={500} placeholder="For example: prefer player props" className="block w-full rounded bg-slate-800 p-2"/></label>
 <button disabled={busy} className="rounded bg-emerald-800 px-4 py-2 disabled:opacity-50">{busy?'Checking offers and requesting AI selection…':'Build research parlay'}</button></form>
 {error&&<p role="alert" className="text-amber-300">{error}</p>}
 {result&&<section aria-live="polite" className="space-y-3 rounded border border-slate-700 p-4"><h2>{result.status.replaceAll('_',' ')}</h2><p>{result.note}</p>
 {result.legs.map((leg,i)=><p key={`${leg.id}:${i}`}>{leg.selection} · individual price {leg.price_american} · model probability {(leg.model_probability*100).toFixed(1)}%</p>)}
 {result.combined_probability!=null&&<p>Independence estimate: {(result.combined_probability*100).toFixed(1)}% · theoretical combined American odds: {result.combined_price_american}. Not a verified payout or demonstrated profitable strategy.</p>}
 </section>}</main>;
}
