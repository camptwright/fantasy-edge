import Link from "next/link";
import {FantasyModels, type DecisionModels} from "./view";
export const dynamic="force-dynamic";
async function api<T>(path:string):Promise<T|null> {
 const token=process.env.FANTASY_API_TOKEN;
 if(!token)return null;
 try {const r=await fetch(`${process.env.FANTASY_API_URL||"http://api:8000"}${path}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:AbortSignal.timeout(20000)}); return r.ok?await r.json():null;} catch{return null;}
}
export default async function Page({searchParams}:{searchParams:Promise<{league?:string}>}) {
 const query=await searchParams;
 const leagues=(await api<{items:{league_id:string;name:string}[]}>("/api/v1/fantasy/leagues"))?.items||[];
 const selected=leagues.find(l=>l.league_id===query.league)||leagues[0];
 const data=selected?await api<DecisionModels>(`/api/v1/fantasy/leagues/${encodeURIComponent(selected.league_id)}/decision-models`):null;
 return <main className="mx-auto max-w-6xl space-y-5 p-5 md:p-10"><h1 className="text-3xl font-bold">Fantasy decision models</h1><p className="text-slate-400">Weekly matchup and roster-aware waiver candidates, separate from rest-of-season research. No automatic transactions.</p><nav className="flex flex-wrap gap-3">{leagues.map(l=><Link className={`rounded border p-3 ${l===selected?"border-emerald-500":"border-slate-700"}`} key={l.league_id} href={`/fantasy/models?league=${encodeURIComponent(l.league_id)}`}>{l.name}</Link>)}</nav>{data?.status==="candidate"?<FantasyModels data={data}/>:<p>Model inputs unavailable: {data?.status||"service unavailable"}.</p>}</main>;
}
