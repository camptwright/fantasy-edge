"use client";
import { useState } from "react";
type Stat = {stat:string;status:string;games:number;baseline?:number;candidate?:number};
export type CollegeLab = {status:string;generated_at?:string;coverage?:Record<string,unknown>;notes?:string[];
 players:{player_id:string;name:string;team:string;conference:string;position:string;game_time:string|null;stats:Stat[]}[];
 metrics:{conference:string;stat:string;samples:number;games:number;baseline_mae:number;candidate_mae:number;usage_blend_samples:number}[]};
export function CollegePlayerLab({data}:{data:CollegeLab}) {
 const teams=Array.from(new Set(data.players.map(p=>p.team))).sort();
 const [team,setTeam]=useState(teams.find(t=>t==="Texas Longhorns")||teams[0]||"");
 const players=data.players.filter(p=>p.team===team);
 const conference=players[0]?.conference;
 return <section className="my-8 space-y-3 rounded-xl border border-slate-700 p-4">
  <h2 className="text-2xl font-semibold">College Player Stat Lab · Power 4</h2>
  <p className="text-sm text-amber-200">Retrospective 2026 evaluation, not pregame-recorded performance. ACC · Big Ten · Big 12 · SEC.</p>
  <p className="text-xs text-slate-400">Updated: {data.generated_at||"Not started"}. Minimum eight prior recorded games; missing history stays unsupported.</p>
  {data.coverage && <details><summary>Data coverage and exclusions</summary><pre className="overflow-x-auto text-xs">{JSON.stringify(data.coverage,null,2)}</pre></details>}
  <label className="block text-sm">Team <select value={team} onChange={e=>setTeam(e.target.value)} className="ml-2 rounded border border-slate-600 bg-slate-900 p-2">{teams.map(t=><option key={t}>{t}</option>)}</select></label>
  {data.status!=="experimental" && <p>College evaluation has not run yet.</p>}
  <details><summary>{conference||"Conference"} completed-game errors (lower MAE is better)</summary>
   <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr>{["Stat","Samples / games","Baseline MAE","Candidate MAE","Usage-adjusted samples"].map(h=><th className="p-2" key={h}>{h}</th>)}</tr></thead><tbody>{data.metrics.filter(m=>m.conference===conference).map(m=><tr key={m.stat}><td className="p-2">{m.stat.replaceAll("_"," ")}</td><td>{m.samples} / {m.games}</td><td>{m.baseline_mae.toFixed(2)}</td><td>{m.candidate_mae.toFixed(2)}</td><td>{m.usage_blend_samples}</td></tr>)}</tbody></table></div>
  </details>
  <div className="grid gap-3 sm:grid-cols-2">{players.map(p=><article key={p.player_id} className="rounded-lg bg-slate-900 p-3"><h3 className="font-semibold">{p.name} · {p.position}</h3><p className="text-xs text-slate-400">{p.game_time ? `Next scheduled kickoff: ${p.game_time}`:"No known upcoming game; historical estimate only"}</p>{p.stats.map(s=><p className="text-sm text-slate-300" key={s.stat}>{s.stat.replaceAll("_"," ")}: {s.status==="ready" ? `${s.baseline?.toFixed(1)} baseline / ${s.candidate?.toFixed(1)} candidate`:`insufficient history (${s.games} games)`}</p>)}</article>)}</div>
  <ul className="list-disc pl-5 text-xs text-slate-400">{data.notes?.map(n=><li key={n}>{n}</li>)}</ul>
 </section>;
}
