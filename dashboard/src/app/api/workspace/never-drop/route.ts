import { NextResponse } from "next/server";

const headers = { "Cache-Control": "no-store" };
const valid = (value: unknown, max: number): value is string =>
  typeof value === "string" && value.length > 0 && value.length <= max && /^[A-Za-z0-9_.:-]+$/.test(value);

/** Add ({on: true}) or remove a player from the league's never-drop list. */
export async function POST(request: Request) {
  const token = process.env.FANTASY_API_TOKEN, base = process.env.FANTASY_API_URL || "http://api:8000";
  if (!token) return NextResponse.json({detail: "Never-drop list unavailable"}, {status: 503, headers});
  try {
    const body = await request.json();
    if (!valid(body.league_id, 80) || !valid(body.player_id, 80) || typeof body.on !== "boolean") {
      return NextResponse.json({detail: "Invalid request"}, {status: 400, headers});
    }
    const league = encodeURIComponent(body.league_id);
    const response = await fetch(body.on ? `${base}/api/v2/personal-fantasy/leagues/${league}/never-drop`
      : `${base}/api/v2/personal-fantasy/leagues/${league}/never-drop/${encodeURIComponent(body.player_id)}`, {
      method: body.on ? "POST" : "DELETE",
      headers: {Authorization: `Bearer ${token}`, "Content-Type": "application/json"},
      body: body.on ? JSON.stringify({player_id: body.player_id}) : undefined,
      cache: "no-store", signal: AbortSignal.timeout(8000),
    });
    return NextResponse.json(await response.json(), {status: response.status, headers});
  } catch { return NextResponse.json({detail: "Could not update the list; retry shortly"}, {status: 503, headers}); }
}
