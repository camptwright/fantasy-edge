import { NextRequest, NextResponse } from "next/server";

// Server-side proxy so FANTASY_API_TOKEN never reaches the browser - same
// convention as ../../advice/route.ts.
export async function POST(request: NextRequest) {
  const token = process.env.FANTASY_API_TOKEN;
  if (!token) return NextResponse.json({ error: "FANTASY_API_TOKEN is not configured" }, { status: 503 });
  const { league_id, side_a_player_ids, side_b_player_ids } = await request.json();
  if (!league_id || !side_a_player_ids?.length || !side_b_player_ids?.length) {
    return NextResponse.json({ error: "league_id and at least one player on each side are required" }, { status: 400 });
  }
  const base = process.env.FANTASY_API_URL || "http://api:8000";
  const response = await fetch(`${base}/api/v1/fantasy/leagues/${league_id}/trade/evaluate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ side_a_player_ids, side_b_player_ids }),
  });
  const body = await response.json().catch(() => ({ error: "The trade service returned a non-JSON response." }));
  return NextResponse.json(body, { status: response.status });
}
