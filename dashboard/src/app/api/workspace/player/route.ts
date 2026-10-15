import { NextResponse } from 'next/server';
export async function GET(request:Request) {
  const headers={'Cache-Control':'no-store'};
  const query=new URL(request.url).searchParams;
  const league=query.get('league'),player=query.get('player'),generated=query.get('generated_at');
  if (!league||!player||league.length>100||player.length>100||(generated&&generated.length>80))return NextResponse.json({detail:'Invalid player selection'},{status:400,headers});
  const base=process.env.FANTASY_WORKSPACE_API_URL,token=process.env.FANTASY_API_TOKEN;
  if (!base||!token)return NextResponse.json({detail:'Service unavailable'},{status:503,headers});
  try {
    const bound=generated?`?${new URLSearchParams({generated_at:generated})}`:'';
    const response=await fetch(`${base}/api/v2/fantasy/leagues/${encodeURIComponent(league)}/players/${encodeURIComponent(player)}${bound}`,{headers:{Authorization:`Bearer ${token}`},cache:'no-store',signal:AbortSignal.timeout(5000)});
    return NextResponse.json(await response.json(),{status:response.status,headers});
  } catch {return NextResponse.json({detail:'Player evidence unavailable'},{status:503,headers});}
}
