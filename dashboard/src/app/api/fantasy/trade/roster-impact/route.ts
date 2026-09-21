import {NextResponse} from "next/server";
export async function POST(request:Request) {
 const token=process.env.FANTASY_API_TOKEN;
 if(!token)return NextResponse.json({error:"Fantasy API unavailable"},{status:503});
 try {
  const {league_id,side_a_player_ids,side_b_player_ids,a,b}=await request.json();
  if(typeof league_id!=="string"||!Array.isArray(side_a_player_ids)||!Array.isArray(side_b_player_ids))return NextResponse.json({error:"Invalid trade request"},{status:400});
  const r=await fetch(`${process.env.FANTASY_API_URL||"http://api:8000"}/api/v1/fantasy/leagues/${encodeURIComponent(league_id)}/trade/roster-impact`,{method:"POST",headers:{Authorization:`Bearer ${token}`,"Content-Type":"application/json"},body:JSON.stringify({side_a_player_ids,side_b_player_ids,a,b}),signal:AbortSignal.timeout(30000)});
  return NextResponse.json(await r.json(),{status:r.status});
 }catch{return NextResponse.json({error:"Trade service unavailable"},{status:503});}
}
