import {LedgerTools} from "./view";
import {LedgerSlip,type QuoteDraft} from "./slip";
import {ReceiptImport} from "./receipts";
export const dynamic="force-dynamic";
type Exposure={gross:string;sport:Record<string,string>;book:Record<string,string>};
const tile="rounded-xl border border-slate-800 bg-slate-900/60 p-4";
type Bet={id:string;mode:string;currency:string;stake:string;terms:Record<string,unknown>;settlement:{status:string;profit?:string};closing:{status:string;price_american?:number;clv_percent?:number;verification?:unknown}};
export default async function Page({searchParams}:{searchParams:Promise<{quote?:string;kind?:string;side?:string}>}){
 const query=await searchParams;
 let draft:QuoteDraft|null=null,evidence:unknown=null;
 async function get(path:string){try{const r=await fetch(`${process.env.FANTASY_API_URL||"http://api:8000"}/api/v1/ledger${path}`,{headers:{Authorization:`Bearer ${process.env.FANTASY_API_TOKEN||""}`},cache:"no-store",signal:AbortSignal.timeout(15000)});return r.ok?await r.json():null;}catch{return null;}}
 [draft,evidence]=await Promise.all([query.quote&&query.kind&&query.side?get(`/quote/${encodeURIComponent(query.kind)}/${encodeURIComponent(query.quote)}?side=${encodeURIComponent(query.side)}`):null,get("/closing-evidence-status")]);
 let data:{items:Bet[];exposure:Record<string,Record<string,Exposure>>;policies:Record<string,unknown>}|null=null;
 try{const r=await fetch(`${process.env.FANTASY_API_URL||"http://api:8000"}/api/v1/ledger`,{headers:{Authorization:`Bearer ${process.env.FANTASY_API_TOKEN||""}`},cache:"no-store",signal:AbortSignal.timeout(15000)});if(r.ok)data=await r.json();}catch{}
  const items=data?.items??[];
  const open=items.filter(b=>b.settlement.status==="open").length;
  const profit=(mode:string)=>items.filter(b=>b.mode===mode&&b.settlement.profit!=null).reduce((sum,b)=>sum+Number(b.settlement.profit),0);
  return <main className="mx-auto max-w-6xl space-y-6 px-4 py-6 md:px-8">
    <header><p className="text-xs font-medium uppercase tracking-wider text-slate-400">Markets</p><h1 className="mt-1 text-2xl font-semibold tracking-tight md:text-3xl">Betting ledger</h1>
      <p className="mt-2 text-sm text-slate-400">Manual and paper singles, settlement audit and gross stake exposure. No automatic betting.</p></header>
    {query.quote&&(draft?<LedgerSlip key={`${query.quote}:${query.side}`} draft={draft}/>:<p role="alert" className="rounded-xl border border-amber-800 p-4 text-sm">The selected quote could not be resolved. Return to Best Bets and refresh; no wager was recorded.</p>)}
    {!data?<p role="status" className="rounded-xl border border-amber-800 p-4 text-sm">Ledger service unavailable. This is a connection error, not an empty ledger.</p>:<>
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className={tile}><dt className="text-xs text-slate-400">Entries</dt><dd className="mt-1 text-2xl font-semibold tabular-nums">{items.length}</dd><dd className="mt-1 text-[11px] text-slate-500">{data.items.filter(b=>b.mode==="actual").length} actual · {data.items.filter(b=>b.mode==="paper").length} paper</dd></div>
        <div className={tile}><dt className="text-xs text-slate-400">Open</dt><dd className="mt-1 text-2xl font-semibold tabular-nums">{open}</dd><dd className="mt-1 text-[11px] text-slate-500">Awaiting settlement</dd></div>
        {(["actual","paper"] as const).map(mode=><div key={mode} className={tile}><dt className="text-xs capitalize text-slate-400">{mode} settled profit</dt><dd className={`mt-1 text-2xl font-semibold tabular-nums ${profit(mode)>0?"text-emerald-300":profit(mode)<0?"text-rose-300":""}`}>{profit(mode).toFixed(2)}</dd><dd className="mt-1 text-[11px] text-slate-500">Mixed currencies are not converted</dd></div>)}
      </dl>
      <p className="rounded-xl border border-amber-700/50 bg-amber-500/5 p-4 text-sm text-amber-100">Verified CLV requires reviewed matching receipt/quote rules AND evidence of an official closing price. Other observations remain labeled proxies. CLV here means same-line decimal-price improvement, not no-vig expected return.</p>
      <section aria-label="Entries"><h2 className="text-lg font-semibold">Entries</h2>
        {!items.length?<p className="mt-2 text-sm text-slate-400">No bets recorded. Recommendations are not wagers.</p>:
        <div className="workspace-scrollbar mt-3 overflow-x-auto rounded-xl border border-slate-800"><table className="w-full min-w-[46rem] text-sm">
          <thead className="bg-slate-900/70 text-xs text-slate-400"><tr>{["Bet","Mode","Stake","Status","Profit","Closing"].map(h=><th key={h} scope="col" className="px-3 py-2 text-left font-medium">{h}</th>)}</tr></thead>
          <tbody>{items.map(b=><tr key={b.id} className="border-t border-slate-800/70 align-top">
            <td className="px-3 py-2">{String(b.terms.book)} · {String(b.terms.market)} · {String(b.terms.side)}{b.terms.line!=null?` ${String(b.terms.line)}`:""}
              <details className="mt-1 text-[11px] text-slate-500"><summary className="cursor-pointer">Frozen evidence</summary><p className="break-all">{b.id}</p><pre className="overflow-auto whitespace-pre-wrap">{JSON.stringify({terms:b.terms,closing:b.closing},null,2)}</pre></details></td>
            <td className="px-3 py-2 capitalize">{b.mode}</td><td className="px-3 py-2 tabular-nums">{b.currency} {b.stake}</td>
            <td className="px-3 py-2 capitalize">{b.settlement.status}</td><td className="px-3 py-2 tabular-nums">{b.settlement.profit??"pending"}</td>
            <td className="px-3 py-2 text-xs">{b.closing.status.replaceAll("_"," ")}{b.closing.price_american!=null?` · ${b.closing.price_american}`:""}{b.closing.clv_percent!=null?` · CLV ${b.closing.clv_percent}%`:""}</td>
          </tr>)}</tbody></table></div>}
      </section>
      <section aria-label="Exposure and controls"><h2 className="text-lg font-semibold">Exposure and controls</h2>
        <p className="mt-1 text-sm text-slate-400">{Object.keys(data.policies).length?"Saved stake limits apply; unset dimensions have no limit.":"Unconfigured — no bankroll or stake limits have been assumed."} Actual and paper stakes are separate; related bets are not netted.</p>
        {!Object.keys(data.exposure).length?<p className="mt-2 text-sm text-slate-500">No open stakes.</p>:
        <ul className="mt-3 grid gap-3 md:grid-cols-2">{Object.entries(data.exposure).flatMap(([currency,modes])=>Object.entries(modes).map(([mode,e])=><li key={currency+mode} className={tile}>
          <p className="flex justify-between text-sm"><span className="capitalize">{mode} · {currency}</span><span className="font-semibold tabular-nums">{e.gross} open</span></p>
          <p className="mt-1 text-xs text-slate-500">{Object.entries(e.sport).map(([k,v])=>`${k.toUpperCase()} ${v}`).join(" · ")||"—"} · {Object.entries(e.book).map(([k,v])=>`${k} ${v}`).join(" · ")}</p></li>))}</ul>}
        {!!Object.keys(data.policies).length&&<details className="mt-2 text-xs text-slate-400"><summary className="cursor-pointer">Saved limits</summary><pre className="overflow-auto whitespace-pre-wrap">{JSON.stringify(data.policies,null,2)}</pre></details>}
      </section>
      <details className="rounded-xl border border-slate-800 p-4"><summary className="min-h-11 cursor-pointer font-medium">Import receipts</summary><ReceiptImport/></details>
      <details className="rounded-xl border border-slate-800 p-4"><summary className="min-h-11 cursor-pointer font-medium">Advanced manual entry, settlements and limits</summary><LedgerTools/></details>
    </>}
    <details className="text-sm text-slate-400"><summary className="min-h-11 cursor-pointer">Closing verification coverage and requirements</summary><pre className="whitespace-pre-wrap text-xs">{JSON.stringify(evidence,null,2)}</pre></details>
  </main>;
}
