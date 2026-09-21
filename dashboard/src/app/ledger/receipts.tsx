"use client";
import {useState} from "react";
import {ledgerAction} from "./actions";
export function ReceiptImport(){
 const [raw,setRaw]=useState(""),[result,setResult]=useState(""),[token,setToken]=useState<string|null>(null),[busy,setBusy]=useState(false);
 function edit(value:string){setRaw(value);setToken(null);setResult("");}
 async function run(commit:boolean){setBusy(true);try{
  const parsed=JSON.parse(raw);delete parsed.preview_sha256;
  const reply=await ledgerAction(commit?"receipts/commit":"receipts/preview",{...parsed,...(commit?{preview_sha256:token}:{})});
  setResult(JSON.stringify(reply,null,2));
  setToken(!commit&&"ok" in reply&&reply.ok&&reply.result.can_commit?reply.result.preview_sha256:null);
 }catch{setResult("Invalid receipt JSON. Use the normalized template; PDF/image OCR is not supported.");setToken(null);}finally{setBusy(false);}}
 return <section className="space-y-3 rounded border border-slate-700 p-4"><h2 className="text-xl">Import receipts</h2><p className="text-sm text-slate-400">Normalized JSON only, up to 100 singles per batch and 256 KB. Files are processed by your app, not an external AI service. Use a local account nickname; remove account numbers, payment information and credentials. Imports record placement claims, not automatic settlements.</p><a href="/ledger-receipt-template.json" download className="text-emerald-300 underline">Download receipt template</a><input aria-label="Receipt JSON file" className="block" type="file" accept=".json,application/json" onChange={async e=>{const file=e.target.files?.[0];if(!file)return;if(file.size>256*1024){setResult("File exceeds 256 KB");setToken(null);return;}edit(await file.text());}}/><textarea aria-label="Receipt JSON" rows={8} className="w-full bg-slate-900 p-3 font-mono text-sm" value={raw} onChange={e=>edit(e.target.value)}/><div className="flex gap-3"><button className="rounded border p-2" disabled={busy||!raw||raw.length>256*1024} onClick={()=>run(false)}>Preview and validate</button><button className="rounded border border-emerald-500 p-2 disabled:opacity-50" disabled={busy||!token} onClick={()=>run(true)}>Confirm import</button></div><pre role="status" className="whitespace-pre-wrap text-sm">{result}</pre></section>;
}
