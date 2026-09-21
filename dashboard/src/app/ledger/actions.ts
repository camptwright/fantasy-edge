"use server";
import {revalidatePath} from "next/cache";
export async function ledgerAction(action:string, body:unknown) {
 if(!["bets","policy","capture-closes","preflight","receipts/preview","receipts/commit"].includes(action) && !/^bets\/[0-9a-f-]{36}\/settlements$/.test(action)) return {error:"Unsupported action"};
 const token=process.env.FANTASY_API_TOKEN;
 if(!token)return {error:"Service unavailable"};
 try {
  const r=await fetch(`${process.env.FANTASY_API_URL||"http://api:8000"}/api/v1/ledger/${action}`,{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
  const result=await r.json();
  if(r.ok)revalidatePath("/ledger");
  return {ok:r.ok,result};
 }catch{return {error:"Request failed. Retry with the SAME request_id to avoid duplicate entries."};}
}
