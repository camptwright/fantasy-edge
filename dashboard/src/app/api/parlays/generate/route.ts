import {NextRequest,NextResponse} from 'next/server';
/** Same-origin proxy to the parlay generator; the API token stays server-side. Nothing is ever placed. */
export async function POST(request:NextRequest){
 let sameOrigin=false;
 try{sameOrigin=new URL(request.headers.get('origin')||'').host===request.headers.get('host');}catch{}
 if(!sameOrigin)return NextResponse.json({detail:'Same-origin request required'},{status:403});
 const token=process.env.FANTASY_API_TOKEN;
 if(!token)return NextResponse.json({detail:'API authentication unavailable'},{status:503});
 try{
  const body=await request.text();
  if(body.length>4096)return NextResponse.json({detail:'Request too large'},{status:413});
  JSON.parse(body);
  const response=await fetch(`${process.env.FANTASY_API_URL||'http://api:8000'}/parlays/generate`,{
   method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},
   body,cache:'no-store',signal:AbortSignal.timeout(45000)});
  return NextResponse.json(await response.json(),{status:response.status});
 }catch{return NextResponse.json({detail:'Generator unavailable or request invalid.'},{status:503});}
}
