import { NextResponse } from 'next/server';
export async function GET(request:Request) {
  const headers={'Cache-Control':'no-store'};
  const league=new URL(request.url).searchParams.get('league');
  if (!league||league.length>100)return NextResponse.json({detail:'Invalid league'},{status:400,headers});
  const base=process.env.FANTASY_WORKSPACE_API_URL,token=process.env.FANTASY_API_TOKEN;
  if (!base||!token)return NextResponse.json({detail:'Service unavailable'},{status:503,headers});
  try {
    const response=await fetch(`${base}/api/v2/fantasy/leagues/${encodeURIComponent(league)}/draft-picks`,{headers:{Authorization:`Bearer ${token}`},cache:'no-store',signal:AbortSignal.timeout(5000)});
    return NextResponse.json(await response.json(),{status:response.status,headers});
  } catch {return NextResponse.json({detail:'Draft picks unavailable'},{status:503,headers});}
}
