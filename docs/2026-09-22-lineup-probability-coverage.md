# Full-lineup probability coverage, September 22

## Delivered and verified

- Free Sleeper weekly actuals backfill: 20 weeks, 29,615 game-linked appearances across 2025 and completed 2026 weeks. Shared archive avoids separate downloads per league. Prior-season refresh is monthly; current-season correction refresh is daily.
- Source records require exact season/week, actual rather than projected stats, a played appearance, and a unique dated team/opponent match to a final local NFL game. Conflicting duplicate appearances are excluded.
- Specialist component scoring uses a bounded vocabulary and must reconcile against the target league's official totals before research use. Missing players, unsupported rules, or failed reconciliation do not qualify.
- Warriors: 24 kicker and 25 defense reconciliation observations, zero mismatches. Aubrey, Bates, Baltimore and Green Bay each have 19 scored games. Full-lineup research simulations now compute instead of withholding for these four missing distributions.
- Lineup search uses a separate random sample from the reported probability estimate. Monte Carlo standard error is explicitly not model uncertainty or proof of calibration.
- API, worker and beat rebuilt and deployed. Repeated worker runs completed; both history passes requested zero already-archived weeks. One immutable full-lineup forecast was captured, without duplicate capture on the second run.
- Full suite: 661 passed, 1 skipped, 20 live tests deselected. After the final simulation stream change: 15 focused tests passed. An earlier run encountered the isolated test database's advisory lock; the successful full rerun occurred after the lock cleared.

## Still not fully validated

No full-lineup forecast outcomes have been graded. `validated` remains false, the serving probability remains null, and the displayed estimates remain research. No models were promoted and no actual lineups were changed.

The ESPN league's 2025 endpoint returns 404. Current-league responses include prior-season aggregate totals, not the weekly distributions needed here; aggregates were not divided into invented weekly history. Its K/DST scoring also cannot be substituted with Sleeper default scoring. ESPN's remaining starter blockers are Packers D/ST, Texans D/ST, Chris Boswell, Harrison Butker, Jadarian Price, KC Concepcion and Carnell Tate. Price additionally requires availability review. ESPN now has two current-season scored weeks, which is insufficient player-specific distribution history.

## Requirements before a validated serving claim

1. Verified ESPN-specific specialist scoring/history (including position overrides and different points-allowed buckets), or an independently evaluated alternative distribution source.
2. A held-out, position/role-aware cold-start distribution model for rookies; do not pretend these players have veteran NFL histories.
3. Verified availability or an evaluated participation model. Do not silently clear injury flags.
4. Sufficient immutable, genuinely pregame full-lineup forecasts with completed outcomes, evaluation of probability reliability against retained baselines, and a version/scoring-bound serving decision. Corrected historical records are not prospective forecasts.

The current pregame capture/grading scheduler is active. Future outcomes cannot be manufactured to satisfy the last requirement.
