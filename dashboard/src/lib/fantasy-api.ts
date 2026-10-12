/** Bounded server reads; transport failure is not a legitimate empty result. */
export async function fantasyApi<T>(path: string, timeoutMs = 20000): Promise<T | null> {
  const token = process.env.FANTASY_API_TOKEN;
  if (!token) return null;
  try {
    const base = path.startsWith("/api/v2/") && process.env.FANTASY_WORKSPACE_API_URL
      ? process.env.FANTASY_WORKSPACE_API_URL : process.env.FANTASY_API_URL || "http://api:8000";
    const response = await fetch(`${base}${path}`, {
      headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
    return response.ok ? await response.json() : null;
  } catch { return null; }
}
