import {createApiLoader} from "@/lib/resilient-api";
export const dynamic="force-dynamic";
type Odds={configured?:boolean;quota_blocked?:boolean;quota_floor?:number;quota_retry_in_seconds?:number;note?:string;telemetry?:{remaining?:number|null;used?:number|null;observed_at?:string};sports?:{sport:string;reason:string;cooldown_seconds:number;window_opens_at?:string|null}[]};
type Provider={configured:boolean;daily_limit:number;reserved_today:number;unit:string;blocked_seconds:number;bookmakers:string[];last_response?:{checked_at?:string;http_status?:number;remaining?:string|null}|null};
type Aggregate={enabled?:boolean;providers?:Record<string,Provider>;note?:string};
type Coverage={generated_at?:string;truncated?:boolean;scope?:string;note?:string;rows_scanned?:number;groups:{source:string;sport:string;offers:number;quote_eligible:number;blockers:Record<string,number>;markets:string[];last_observed_at:string|null;last_confirmed_at:string|null}[]};
const label=(s:string)=>s.replaceAll("_"," ");
export default async function Providers(){
 const {fetchJson,failures}=createApiLoader();
 const [odds,aggregate,coverage]=await Promise.all([
  fetchJson<Odds>("/calibration/odds-status",{}),fetchJson<Aggregate>("/calibration/prop-provider-status",{}),
  fetchJson<Coverage>("/calibration/provider-coverage",{groups:[]})]);
 return <main className="mx-auto max-w-6xl space-y-6 p-6"><h1 className="text-3xl font-semibold">Provider coverage & quota</h1>
 <p className="text-slate-400">Read-only telemetry. Opening this page makes no provider requests and spends no provider credits.</p>
 {failures.length>0&&<p role="alert" className="text-amber-200">Some telemetry is unavailable: {failures.join(", ")}. Missing values are unknown, not zero.</p>}
 <section className="rounded-xl border border-slate-700 p-4"><h2 className="text-xl">The Odds API</h2>
 <p>Configured: {odds.configured==null?"unknown":String(odds.configured)} · Quota guard: {odds.quota_blocked==null?"unknown":odds.quota_blocked?"blocked":"not blocked"}</p>
 <p>Last reported remaining: {odds.telemetry?.remaining??"unknown"} · Used: {odds.telemetry?.used??"unknown"} · Reserve floor: {odds.quota_floor??"unknown"}</p>
 <p className="text-sm text-slate-400">Observed: {odds.telemetry?.observed_at||"never"}. Guard retry in {odds.quota_retry_in_seconds??"unknown"} seconds—not a provider reset time.</p>
 {odds.sports?.map(s=><p key={s.sport} className="py-1">{s.sport.toUpperCase()}: {label(s.reason)} · cooldown {s.cooldown_seconds}s{s.window_opens_at?` · collection window ${s.window_opens_at}`:""}</p>)}
 <p className="mt-2 text-xs text-slate-400">{odds.note}</p></section>
 <section className="grid gap-4 sm:grid-cols-2">{Object.entries(aggregate.providers||{}).map(([key,p])=><article key={key} className="rounded-xl border border-slate-700 p-4"><h2 className="text-xl">{key==="sgo"?"SportsGameOdds":"ParlayAPI"}</h2>
 <p>Collection enabled: {String(aggregate.enabled)} · Key configured: {String(p.configured)}</p>
 <p>Local daily reservations: {p.reserved_today} / {p.daily_limit} {p.unit}</p><p>Local budget headroom: {Math.max(0,p.daily_limit-p.reserved_today)} {p.unit}</p>
 <p className="text-sm">Provider-reported remaining: {p.last_response?.remaining??"unknown"} · Blocked for: {p.blocked_seconds}s</p>
 <p className="text-xs text-slate-400">Daily reservations use UTC and are not the provider account balance. Last HTTP: {p.last_response?.http_status??"unknown"} · {p.last_response?.checked_at||"never"}</p>
 <p className="mt-2 text-sm">Configured books: {p.bookmakers.join(", ")}</p></article>)}</section>
 <section className="space-y-3"><h2 className="text-xl">Why offers are not reaching the model</h2><p className="text-sm">{coverage.scope}</p><p className="text-xs text-slate-400">Updated {coverage.generated_at||"unknown"} · {coverage.rows_scanned??"unknown"} observations scanned. {coverage.note}</p>
 {coverage.truncated&&<p className="text-amber-200">Sample capped at 20,000 observations. Counts are partial, not full-provider totals.</p>}
 {!coverage.groups.length&&<p>No quote groups returned. Check telemetry availability and collection windows before assuming a model problem.</p>}
 {coverage.groups.map(g=><article key={`${g.source}:${g.sport}`} className="rounded-xl border border-slate-700 p-4"><h3 className="font-semibold">{g.source} · {g.sport.toUpperCase()}</h3><p>{g.offers} distinct observed offers → {g.quote_eligible} pass quote availability checks</p>
 <p className="text-amber-200">{Object.entries(g.blockers).map(([k,v])=>`${label(k)}: ${v}`).join(" · ")||"No quote-availability blockers in this sample"}</p>
 <p className="text-xs text-slate-400">Last quote: {g.last_observed_at||"unknown"} · Last confirmation: {g.last_confirmed_at||"unknown"}</p><details><summary className="text-sm">Observed markets ({g.markets.length})</summary><p className="text-xs">{g.markets.map(label).join(", ")}</p></details></article>)}
 <p className="text-sm">Passing these checks is only the first gate. <a className="underline" href="/calibration">Calibration</a> shows model readiness; <a className="underline" href="/best-bets">Best Bets</a> shows actionable outputs.</p></section>
 </main>;
}
