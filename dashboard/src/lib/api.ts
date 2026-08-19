// Relative `/api/...` paths only - CONSTRAINT #11's nginx config proxies
// `/api/` to the FastAPI backend on the same origin (`/` -> dashboard :3000,
// `/api/` -> api :8000), so the browser never needs to know the backend's
// actual host/port and this works identically in dev (via next.config.js
// rewrites, added below) and behind nginx in production.

const API_BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function fetcher<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(body.detail ?? res.statusText, res.status);
  }
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new ApiError(errBody.detail ?? res.statusText, res.status);
  }
  return res.json();
}

export const sportsApi = {
  overview: () => fetcher<import("@/lib/types").SportsOverview>("/v1/overview"),
  teamOdds: (query = "") => fetcher<import("@/lib/types").MarketResponse>(`/v1/team-odds${query}`),
  playerOdds: (query = "") => fetcher<import("@/lib/types").MarketResponse>(`/v1/player-odds${query}`),
  games: (query = "") => fetcher<import("@/lib/types").GamesResponse>(`/v1/games${query}`),
  favorites: () => fetcher<import("@/lib/types").FavoritesResponse>("/v1/favorites"),
};
