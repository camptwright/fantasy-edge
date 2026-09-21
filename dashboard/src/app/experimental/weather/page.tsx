import {createApiLoader} from "@/lib/resilient-api";
export const dynamic="force-dynamic";
export default async function Page(){
 const {fetchJson}=createApiLoader();
 const data=await fetchJson<Record<string,unknown>>("/experiments/weather-context",{status:"unavailable"});
 return <main className="mx-auto max-w-5xl space-y-4 p-6"><h1 className="text-3xl">Event venue and weather research</h1><p>Hourly source archives for up to eight upcoming games per sport within 72 hours. MLB event venues provide coordinates; football venue IDs can be bound while coordinates remain missing. No home-stadium substitution.</p><p>Retractable roofs remain unconfirmed. Forecast snapshots are research covariates, not trained probability adjustments. Serving models are unchanged.</p><pre className="overflow-auto rounded bg-slate-900 p-4 text-sm">{JSON.stringify(data,null,2)}</pre></main>;
}
