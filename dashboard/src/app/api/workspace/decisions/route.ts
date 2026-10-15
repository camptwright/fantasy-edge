import { NextResponse } from "next/server";

const headers = { "Cache-Control": "no-store" };
const credentials = () => ({ token: process.env.FANTASY_API_TOKEN, base: process.env.FANTASY_API_URL || "http://api:8000" });
const validLeague = (value: unknown): value is string => typeof value === "string" && value.length > 0 && value.length <= 80;

export async function GET(request: Request) {
  const {token, base} = credentials();
  if (!token) return NextResponse.json({detail: "Decision journal unavailable"}, {status: 503, headers});
  const league = new URL(request.url).searchParams.get("league");
  if (!validLeague(league)) return NextResponse.json({detail: "Choose a league"}, {status: 400, headers});
  try {
    const response = await fetch(`${base}/api/v2/personal-fantasy/leagues/${encodeURIComponent(league)}/decisions`, {
      headers: {Authorization: `Bearer ${token}`}, cache: "no-store", signal: AbortSignal.timeout(8000),
    });
    return NextResponse.json(await response.json(), {status: response.status, headers});
  } catch { return NextResponse.json({detail: "Decision history unavailable; retry shortly"}, {status: 503, headers}); }
}

export async function POST(request: Request) {
  const {token, base} = credentials();
  if (!token) return NextResponse.json({detail: "Decision journal unavailable"}, {status: 503, headers});
  try {
    const body = await request.json();
    if (!validLeague(body.league_id) || !["start", "pickup", "trade"].includes(body.action) ||
        typeof body.generated_at !== "string" || body.generated_at.length > 80 ||
        typeof body.request_id !== "string" || body.request_id.length > 40 ||
        typeof (body.note ?? "") !== "string" || (body.note ?? "").length > 1000 ||
        ![body.player_ids, body.counterparty_player_ids ?? []].every(ids => Array.isArray(ids) && ids.length <= 30 &&
          ids.every(id => typeof id === "string" && id.length > 0 && id.length <= 80))) {
      return NextResponse.json({detail: "Invalid decision"}, {status: 400, headers});
    }
    const response = await fetch(`${base}/api/v2/personal-fantasy/leagues/${encodeURIComponent(body.league_id)}/decisions`, {
      method: "POST", headers: {Authorization: `Bearer ${token}`, "Content-Type": "application/json"},
      body: JSON.stringify({request_id: body.request_id, generated_at: body.generated_at, action: body.action,
        player_ids: body.player_ids, counterparty_player_ids: body.counterparty_player_ids ?? [], note: body.note ?? ""}),
      cache: "no-store", signal: AbortSignal.timeout(8000),
    });
    return NextResponse.json(await response.json(), {status: response.status, headers});
  } catch { return NextResponse.json({detail: "Could not save decision; refresh and retry"}, {status: 503, headers}); }
}
