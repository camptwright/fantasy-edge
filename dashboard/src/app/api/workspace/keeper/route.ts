import { NextResponse } from 'next/server';

export async function GET(request: Request) {
  const headers={'Cache-Control':'no-store'};
  const token=process.env.FANTASY_API_TOKEN,base=process.env.FANTASY_WORKSPACE_API_URL;
  const query=new URL(request.url).searchParams;
  const league=query.get('league_id'),player=query.get('player_id');
  if(!league || !player || league.length>100 || player.length>64)
    return NextResponse.json({detail:'Invalid player'},{status:400,headers});
  if(!token || !base)return NextResponse.json({detail:'Preview unavailable'},{status:503,headers});
  try {
    const response=await fetch(`${base}/api/v2/fantasy/leagues/${encodeURIComponent(league)}/keeper-history/${encodeURIComponent(player)}`,{
      headers:{Authorization:`Bearer ${token}`},cache:'no-store',signal:AbortSignal.timeout(8000)});
    return NextResponse.json(await response.json(),{status:response.status,headers});
  }catch{return NextResponse.json({detail:'History unavailable'},{status:503,headers});}
}

export async function POST(request: Request) {
  const headers = {'Cache-Control':'no-store'};
  const token=process.env.FANTASY_API_TOKEN, base=process.env.FANTASY_WORKSPACE_API_URL;
  if (!token || !base) return NextResponse.json({detail:'Preview unavailable'},{status:503,headers});
  try {
    const {league_id,players}=await request.json();
    if (typeof league_id!=='string' || league_id.length>100 || !Array.isArray(players) || players.length!==1)
      return NextResponse.json({detail:'Choose one player'},{status:400,headers});
    const response=await fetch(`${base}/api/v2/fantasy/leagues/${encodeURIComponent(league_id)}/keeper-preview`,{
      method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},
      body:JSON.stringify({players}),cache:'no-store',signal:AbortSignal.timeout(8000)});
    return NextResponse.json(await response.json(),{status:response.status,headers});
  } catch {
    return NextResponse.json({detail:'Keeper review unavailable; retry later'},{status:503,headers});
  }
}
