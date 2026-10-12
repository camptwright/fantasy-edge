import {NextRequest,NextResponse} from 'next/server';
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
  const response=await fetch(`${process.env.FANTASY_API_URL||'http://api:8000'}/parlays/assist`,{
   method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},
   body,cache:'no-store',signal:AbortSignal.timeout(30000)});
  return NextResponse.json(await response.json(),{status:response.status});
 }catch{return NextResponse.json({detail:'Assistant unavailable or request invalid; no wager was placed.'},{status:503});}
}
