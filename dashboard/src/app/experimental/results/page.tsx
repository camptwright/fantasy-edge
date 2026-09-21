import {createApiLoader} from "@/lib/resilient-api";
export const dynamic="force-dynamic";
type Queue={total:number;counts:Record<string,number>;scope?:string;truncated?:boolean;items:{game_id:string;player_id:string;name:string;stat:string;sport:string;reason:string;action:string;next_retry_at:string|null}[]};
export default async function Results(){
 const {fetchJson,failures}=createApiLoader();
 const q=await fetchJson<Queue>("/experiments/missing-results",{total:0,counts:{},items:[]});
 return <main className="mx-auto max-w-6xl space-y-4 p-6"><a href="/experimental">← Experimental</a><h1 className="text-2xl font-semibold">Shared missing-result queue</h1>
 {failures.length>0 ? <p role="alert">Queue temporarily unavailable. This does not mean there are no missing results.</p>:<><p>{q.scope}</p><p>{q.total} unresolved outcomes. Missing is not zero, DNP, or a bookmaker void.</p>
 {Object.entries(q.counts).map(([k,v])=><p key={k}>{k.replaceAll("_"," ")}: {v}</p>)}
 {q.truncated&&<p>Showing the first 200 items; counts cover the complete queue.</p>}
 {q.items.map(r=><article className="rounded border border-slate-700 p-3" key={`${r.game_id}:${r.player_id}:${r.stat}`}><h2>{r.name} · {r.sport.toUpperCase()} · {r.stat.replaceAll("_"," ")}</h2><p>{r.reason.replaceAll("_"," ")} · {r.action.replaceAll("_"," ")}</p><p className="text-xs text-slate-400">Game: {r.game_id} · Next provider retry: {r.next_retry_at||"not tracked"}</p></article>)}</>}
 </main>;
}
