import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const headers = { "Cache-Control": "no-store" };
  const token = process.env.FANTASY_API_TOKEN;
  const base = process.env.FANTASY_WORKSPACE_API_URL;
  if (!token || !base) return NextResponse.json({ detail: "Preview service unavailable" }, { status: 503, headers });
  try {
    const { league_id, generated_at, side_a, side_b, a = {add:[],drop:[]}, b = {add:[],drop:[]} } = await request.json();
    if (typeof league_id !== "string" || league_id.length > 100 || typeof generated_at !== "string"
        || ![side_a, side_b].every(ids => Array.isArray(ids) && ids.length > 0 && ids.length <= 6
          && ids.every(id => typeof id === "string" && id.length <= 100))) {
      return NextResponse.json({ detail: "Invalid package" }, { status: 400, headers });
    }
    if (![a,b].every(plan => plan && [plan.add, plan.drop].every(ids => Array.isArray(ids) && ids.length <= 6 && ids.every(id => typeof id === 'string' && id.length <= 100)))) {
      return NextResponse.json({ detail: "Invalid adjustment plan" }, { status: 400, headers });
    }
    const response = await fetch(`${base}/api/v2/fantasy/leagues/${encodeURIComponent(league_id)}/trade-preview`, {
      method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ generated_at, side_a, side_b, a, b }), cache: "no-store", signal: AbortSignal.timeout(8000),
    });
    const retry = response.headers.get('Retry-After');
    return NextResponse.json(await response.json(), { status: response.status, headers: {...headers, ...(retry ? {'Retry-After':retry} : {})} });
  } catch {
    return NextResponse.json({ detail: "Trade preview unavailable; refresh and retry" }, { status: 503, headers });
  }
}
