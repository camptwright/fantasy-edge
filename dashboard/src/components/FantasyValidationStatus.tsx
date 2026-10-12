export type ProviderEvidence = {
  counts?: Record<string, number>;
  observation_counts?: {
    captures: number; unique_league_player_games: number;
    unique_graded_league_player_games: number; additional_versioned_captures: number;
    captures_by_recipe: Record<string, number>;
  };
};
type Evidence = {
  lineup_simulation?: { player_blockers?: { player_id: string; name: string; reasons: string[]; platform_history_games: number }[] };
  prospective?: { result_backlog?: {blocked_captures:number;unique_player_games:number;unique_games:number;additional_captures:number;player_games_by_blocker:Record<string,number>}; provider_weekly?: ProviderEvidence; lineup_experiments?: { forecasts: number; metrics: unknown[] }; weekly?: { counts: Record<string, number> } };
};

export function FantasyValidationStatus({ data }: { data: Evidence }) {
  const blockers = data.lineup_simulation?.player_blockers ?? [];
  const experiments = data.prospective?.lineup_experiments;
  const pending = data.prospective?.weekly?.counts.awaiting_final_platform_snapshot ?? 0;
  const provider = data.prospective?.provider_weekly;
  const observations = provider?.observation_counts;
  const backlog = data.prospective?.result_backlog;
  return <section className="rounded border border-slate-700 p-4" aria-label="Fantasy validation readiness">
    <h2 className="text-xl">What still needs evidence</h2>
    {backlog && <div className="mt-3" aria-label="Missing-result repair targets"><h3 className="font-semibold">Missing-result repair targets · all configured leagues</h3><p>{backlog.blocked_captures} blocked captures represent {backlog.unique_player_games} distinct player-games across {backlog.unique_games} games. {backlog.additional_captures} repeated captures are not additional missing outcomes.</p><ul className="my-2 text-sm">{Object.entries(backlog.player_games_by_blocker).map(([reason,count])=><li key={reason}>{reason.replaceAll('_',' ')}: {count} player-games</li>)}</ul><p className="text-sm text-slate-400">Counts may overlap across blockers. Missing player rows do not establish zero points or nonparticipation; result recovery must preserve exact player/game and scoring evidence.</p></div>}
    <h3 className="mt-3 font-semibold">Provider forecast evidence · all configured leagues</h3>
    {observations ? <>
      <p>{observations.captures} captures · {observations.unique_league_player_games} unique league/player/game observations · {observations.unique_graded_league_player_games} unique graded observations.</p>
      <p>{observations.additional_versioned_captures} additional versioned captures are not new outcomes.</p>
      <ul className="my-2 text-sm">{Object.entries(observations.captures_by_recipe).sort(([a],[b])=>a.localeCompare(b)).map(([recipe,count])=><li key={recipe}>{recipe === "provider_weekly_v1" ? "Legacy forecasts (v1)" : recipe === "provider_weekly_v2" ? "Scoring-rule-bound forecasts (v2)" : recipe}: {count} captures</li>)}</ul>
      <p className="text-sm text-slate-400">Counts are not independent sample sizes. Players in the same game and across leagues are correlated; versioned captures are not pooled performance evidence.</p>
    </> : <p>Distinct-observation accounting is not available in the latest report.</p>}
    {provider?.counts && <ul className="my-2 text-sm" aria-label="Provider grading status">{Object.entries(provider.counts).sort(([a],[b])=>a.localeCompare(b)).map(([status,count])=><li key={status}>{status.replaceAll("_"," ")}: {count} captures</li>)}</ul>}
    {blockers.length > 0 && <ul className="mt-2 space-y-2">{blockers.map(p => <li key={p.player_id}>
      <strong>{p.name}</strong>: {p.reasons.map(r => r.replaceAll("_", " ")).join("; ")}
      {p.reasons.includes("incomplete_scoring_distribution") && <span> · {p.platform_history_games} platform-history games. A complete eligible scoring distribution is required; a point estimate alone is insufficient.</span>}
    </li>)}</ul>}
    <p className="mt-2">{experiments ? `${experiments.forecasts} frozen lineup experiments; ${experiments.metrics.length} graded version/league summaries.` : "Lineup validation evidence unavailable."}</p>
    {pending > 0 && <p>{pending} weekly captures await a final platform snapshot. These are not graded evidence.</p>}
    <p className="text-sm text-amber-200">Player-point forecast counts span model versions and are not matchup-probability validation. Research estimates remain unvalidated; no automatic promotion or lineup change.</p>
  </section>;
}
