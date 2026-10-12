import {createApiLoader} from "@/lib/resilient-api";
export const dynamic="force-dynamic";
type Row={samples:number;p50_ms:number;p95_ms:number;max_response_bytes:number;server_errors:number};
type Status={status:string;alerts:string[];scope?:string;latest?:{at:string;performance:{peak_rss_bytes?:number;routes?:Record<string,Row>;fantasy_reads?:Record<string,number>}};history:{at:string;api_status:string;alerts:string[]}[]};
export default async function Operations(){
 const {fetchJson}=createApiLoader();
 const data=await fetchJson<Status>("/operations/history",{status:"unavailable",alerts:["Monitoring unavailable"],history:[]});
 const reads=data.latest?.performance.fantasy_reads;
 const attempts=(reads?.checkpoint_hit||0)+(reads?.checkpoint_miss||0);
 return <main className="mx-auto max-w-6xl space-y-5 p-6"><h1 className="text-3xl">Operations & performance</h1><p>Status: {data.status} · Last observation: {data.latest?.at||"none"}</p><p>{data.scope}</p>
 <section><h2 className="text-xl">Needs attention</h2>{data.alerts.length?data.alerts.map(a=><p className="text-amber-300" key={a}>{a}</p>):<p>No alerts in the latest observation. This is not a complete health certification.</p>}</section>
 <p>API process peak memory: {data.latest?.performance.peak_rss_bytes!=null?`${(data.latest.performance.peak_rss_bytes/1048576).toFixed(1)} MiB`:"unknown"}</p>
 <section><h2 className="text-xl">Fantasy calculation paths</h2><p>{reads?`Background checkpoint: ${reads.checkpoint_hit||0} hits / ${reads.checkpoint_miss||0} misses · ${attempts?`${(100*(reads.checkpoint_hit||0)/attempts).toFixed(1)}% hit rate`:"no lookups yet"}`:"Awaiting an observation with fantasy calculation metrics."}</p>{reads&&<p>Custom calculations: {reads.custom_request||0} · completed builds: {reads.generated||0} · failed builds: {reads.generation_failed||0}</p>}<p className="text-sm text-slate-400">Cumulative for the observed API process; resets on restart. Shared concurrent requests count once. Custom requests are excluded from the checkpoint hit rate. A completed build does not imply model qualification.</p></section>
 <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th>Route</th><th>Samples</th><th>p50 ms</th><th>p95 ms</th><th>5xx</th></tr></thead><tbody>{Object.entries(data.latest?.performance.routes||{}).map(([path,r])=><tr key={path}><td>{path}</td><td>{r.samples}</td><td>{r.p50_ms}</td><td>{r.p95_ms}</td><td>{r.server_errors}</td></tr>)}</tbody></table></div>
 <details><summary>Recent durable observations ({data.history.length})</summary>{[...data.history].reverse().map((r,i)=><p key={`${r.at}:${i}`}>{r.at} · {r.api_status} · {r.alerts.join(", ")||"no alerts"}</p>)}</details></main>;
}
