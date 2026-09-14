// Request-scoped loader: no stale cache, no shared failure state, no retries
// that amplify load while the API is restarting or unavailable.
export function createApiLoader(fetcher: typeof fetch = fetch) {
  const failures: string[] = [];
  async function fetchJson<T>(path: string, fallback: T): Promise<T> {
    try {
      const base = process.env.FANTASY_API_URL || "http://api:8000";
      const response = await fetcher(`${base}${path}`, {
        cache: "no-store",
        headers: { Authorization: `Bearer ${process.env.FANTASY_API_TOKEN || ""}` },
        signal: AbortSignal.timeout(20000),
      });
      if (!response.ok) throw new Error("API unavailable");
      // Await inside try: a socket may close while reading the body too.
      const data = await response.json();
      if (data === null || typeof data !== "object" ||
          Array.isArray(data) !== Array.isArray(fallback)) {
        throw new Error("Invalid API response");
      }
      return data as T;
    } catch {
      failures.push(path);
      return fallback;
    }
  }
  return { fetchJson, failures };
}
