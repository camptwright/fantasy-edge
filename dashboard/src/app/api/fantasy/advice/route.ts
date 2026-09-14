import { NextRequest, NextResponse } from "next/server";

// Server-side proxy so FANTASY_API_TOKEN never reaches the browser - same
// convention the stocks tile in the other dashboard already uses for its
// own bearer-token-holding backend. The real /advice call can take a
// while on this app's local, CPU-only LiteLLM model (observed 7-190s
// depending on whether the model is already warm in Ollama's memory), so
// this route sets no artificial timeout of its own - the client button
// is what shows a "still generating" state, not this proxy.
export async function POST(request: NextRequest) {
  const token = process.env.FANTASY_API_TOKEN;
  if (!token) return NextResponse.json({ error: "FANTASY_API_TOKEN is not configured" }, { status: 503 });
  const { league_id } = await request.json();
  if (!league_id) return NextResponse.json({ error: "league_id is required" }, { status: 400 });
  const base = process.env.FANTASY_API_URL || "http://api:8000";
  const response = await fetch(`${base}/api/v1/fantasy/leagues/${league_id}/advice`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = await response.json().catch(() => ({ error: "The advice service returned a non-JSON response." }));
  return NextResponse.json(body, { status: response.status });
}
