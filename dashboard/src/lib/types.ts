// Mirrors the FastAPI routers' response shapes (src/api/routers/*.py on the
// backend). Kept as plain interfaces, not generated - the API surface is
// small and stable enough that codegen would be more ceremony than value.

export interface Game {
  id: string;
  sport: string;
  home_team_name: string | null;
  away_team_name: string | null;
  game_time: string | null;
  status: string;
  home_score: number | null;
  away_score: number | null;
}

export interface Signal {
  id: string;
  sport: string;
  market: string;
  selection: string;
  bookmaker: string;
  price_american: number | null;
  model_probability: number;
  ev_percent: number;
  tier: string | null;
  confidence: string | null;
  stake_units: number | null;
  matchup: string;
  game_time: string | null;
  game_status: string;
}

export interface PropLine {
  id: string;
  sport: string;
  source: string;
  player_name: string;
  stat_type: string;
  line: number;
  over_price_american: number | null;
  under_price_american: number | null;
  edge_percent: number | null;
  captured_at: string;
}

export interface BestPropLine extends PropLine {
  cross_source_spread: number;
  sources: { source: string; line: number; captured_at: string }[];
  matchup: string | null;
  game_time: string | null;
}

export interface Parlay {
  id: string;
  sport: string | null;
  title: string | null;
  rationale: string | null;
  combined_odds_american: number | null;
  ev_percent: number | null;
  result: string | null;
  created_at: string;
}

export interface RankingRow {
  team_id: string;
  team_name: string;
  elo_rating: number;
  rank: number;
  as_of: string;
}

export interface Projection {
  player_name: string;
  stat_type: string;
  projected_value: number;
  source: string;
  captured_at: string;
}

export type MarketStatus =
  | "qualified"
  | "stale"
  | "coverage_incomplete"
  | "uncalibrated"
  | "unsupported_market"
  | "cannot_price_correlation";

export interface SportsSourceRef {
  provider: string;
  snapshot_id: string;
  observed_at: string;
}

export interface MarketAssessment {
  id: string;
  sport: string;
  league: string;
  event_id: string;
  market: string;
  selection: string;
  status: MarketStatus;
  status_reason: string | null;
  probability: number | null;
  fair_price_american: number | null;
  line: number | null;
  price_american: number | null;
  bookmaker: string | null;
  player_name: string | null;
  side: "over" | "under" | null;
  edge_percent: number | null;
  estimated_value_percent: number | null;
  model_version: string | null;
  calibration_label: string | null;
  sources: SportsSourceRef[];
  assessed_at: string;
}

export interface SportsModelHealth {
  model_version: string;
  coverage: Record<string, boolean>;
  calibration: Record<string, number | null>;
  last_successful_ingest: string | null;
  status: "healthy" | "degraded" | "unavailable";
}

export interface SportsOverview {
  qualified: MarketAssessment[];
  watchlist: MarketAssessment[];
  no_bet: MarketAssessment[];
  freshness: { newest_observation: string; age_seconds: number; status: "current" | "stale" | "unavailable" } | null;
  model_health: SportsModelHealth | null;
}

export interface SportsGame {
  id: string;
  sport: string;
  league: string;
  start_time: string | null;
  home_team: string | null;
  away_team: string | null;
  status: string;
}

export interface MarketResponse {
  items: MarketAssessment[];
  next_cursor: string | null;
}

export interface GamesResponse {
  items: SportsGame[];
  next_cursor: string | null;
}

export interface GameDetailResponse {
  game: SportsGame;
  team_lines: MarketAssessment[];
  player_props: MarketAssessment[];
}

export interface Favorite {
  id: string;
  kind: "team" | "player";
  canonical_id: string;
  display_name: string;
  sport: string;
}

export interface FavoritesResponse {
  items: Favorite[];
}
