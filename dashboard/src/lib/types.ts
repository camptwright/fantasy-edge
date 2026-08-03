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
