import {createApiLoader} from "@/lib/resilient-api";
export const dynamic="force-dynamic";
type Queue={total:number|null;status?:string;stale?:boolean;generated_at?:string|null;next_offset?:number|null;counts:Record<string,number>;scope?:string;truncated?:boolean;items:{game_id:string;player_id:string;name:string;stat:string;sport:string;reason:string;action:string;next_retry_at:string|null}[]};
export default async function Results({searchParams}:{searchParams:Promise<{offset?:string}>}){
 const query=await searchParams;const offset=Math.max(0,Number.parseInt(query.offset||"0",10)||0);
 const {fetchJson,failures}=createApiLoader();
 const q=await fetchJson<Queue>(`/experiments/missing-results?offset=${offset}`,{total:null,counts:{},items:[]});
 return <main className="mx-auto max-w-6xl space-y-4 p-6"><a href="/experimental">← Experimental</a><h1 className="text-2xl font-semibold">Shared missing-result queue</h1>
 {failures.length>0 || q.total==null ? <p role="alert">Queue snapshot pending or unavailable. This does not mean there are no missing results.</p>:<><p>{q.scope}</p><p>{q.total} unresolved outcomes. Missing is not zero, DNP, or a bookmaker void.</p><p>Snapshot: {q.generated_at||"unknown"}{q.stale?" · STALE: refresh pending":""}</p>
 {Object.entries(q.counts).map(([k,v])=><p key={k}>{k.replaceAll("_"," ")}: {v}</p>)}
 <nav className="flex gap-4">{offset>0&&<a href={`/experimental/results?offset=${Math.max(0,offset-200)}`}>Previous</a>}{q.next_offset!=null&&<a href={`/experimental/results?offset=${q.next_offset}`}>Next</a>}</nav>
 {q.truncated&&<p>Showing up to 200 items from offset {offset}; counts cover the complete snapshot.</p>}
 {q.items.map(r=><article className="rounded border border-slate-700 p-3" key={`${r.game_id}:${r.player_id}:${r.stat}`}><h2>{r.name} · {r.sport.toUpperCase()} · {r.stat.replaceAll("_"," ")}</h2><p>{r.reason.replaceAll("_"," ")} · {r.action.replaceAll("_"," ")}</p><p className="text-xs text-slate-400">Game: {r.game_id} · Next provider retry: {r.next_retry_at||"not tracked"}</p></article>)}</>}
 </main>;
}
