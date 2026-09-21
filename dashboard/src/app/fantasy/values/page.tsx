import Link from "next/link";
import {Values, type ValueData} from "./view";
export const dynamic="force-dynamic";
async function api<T>(path:string):Promise<T|null> {
 const token=process.env.FANTASY_API_TOKEN;if(!token)return null;
 try {const r=await fetch(`${process.env.FANTASY_API_URL||"http://api:8000"}${path}`,{headers:{Authorization:`Bearer ${token}`},cache:"no-store",signal:AbortSignal.timeout(30000)});return r.ok?await r.json():null;}catch{return null;}
}
export default async function Page({searchParams}:{searchParams:Promise<{league?:string}>}) {
 const query=await searchParams;
 const leagues=(await api<{items:{league_id:string;name:string}[]}>("/api/v1/fantasy/leagues"))?.items||[];
 const selected=leagues.find(l=>l.league_id===query.league)||leagues[0];
 const data=selected?await api<ValueData>(`/api/v1/fantasy/leagues/${encodeURIComponent(selected.league_id)}/player-values`):null;
 return <main className="mx-auto max-w-6xl space-y-5 p-5 md:p-10"><h1 className="text-3xl font-bold">Player values & roster impact</h1><p className="text-slate-400">League-scored production, replacement options, and two-sided trade research. No automatic transactions or market-price claims.</p><nav className="flex flex-wrap gap-3">{leagues.map(l=><Link className="rounded border border-slate-700 p-3" key={l.league_id} href={`/fantasy/values?league=${encodeURIComponent(l.league_id)}`}>{l.name}</Link>)}</nav>{data?.status==="candidate"?<Values key={selected?.league_id} data={data}/>:<p>Inputs unavailable: {data?.status||"service unavailable"}.</p>}</main>;
}
