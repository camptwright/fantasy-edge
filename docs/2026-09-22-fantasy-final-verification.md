# FF implementation and final verification

This supersedes the implementation-gap lists in the earlier September 22
fantasy notes; their measurements remain historical observations.

## Implemented

- Shared recommendation, matchup and advice decision source; removed the
  unused duplicate lineup builder. Unknown scores remain null.
- Lock-preserving lineup/waiver decisions keep started or unbound starters
  in their exact slots, exclude locked bench players, and compare only
  unstarted-slot gains. Missing platform starters fail closed.
- Fresh provider estimates can fall back to recent complete league-scored
  history, explicitly labelled as an estimate. Unpriced context stays visible.
- Bounded legal-lineup enumeration compares win probability against the
  specific opponent. It discloses truncation and uses shared historical-week
  residual draws only when at least eight joint weeks exist; otherwise its
  independent-player assumption is explicit.
- First eligible pregame lineup experiments freeze player evidence, model
  version and scoring-rule identity. Grading requires final, post-final
  platform results under matching rules; win/tie outcomes and Brier metrics
  remain research-only with no automatic promotion.
- Matching current/upcoming-week snapshot selection and best-effort planning
  collection for Sleeper and ESPN. ESPN slot order is normalized consistently.
- Provider-scored history for both platforms supports exact platform player
  IDs, K/DST and rookie coverage without pretending kicking components equal
  complete fantasy scores. ESPN fingerprints include official position overrides.

## ESPN historical repair

Live request with `scoringPeriodId=1` returned 224 actual player-stat records.
The current-period roster response did not contain those historical weekly
records. Collection now explicitly requests each eligible completed week,
checks response period and scoring rules, and refreshes successful history
daily. Current sync continues if optional history/planning requests fail.

After deployment, week-one ESPN history contains 224 player totals.
No historical placement, forecast or missing score was fabricated.

## Verification

- Full isolated-database suite: 657 passed, one intentional skip, 20 live
  tests deselected. Dashboard production build/type checking passed.
- API, worker, beat and local port-13000 preview updated. Prior preview
  retained as `fantasy-edge-grading-preview-before-20260922T214503`.
- ESPN ingestion and prospective evaluation ran twice successfully in the
  same worker process. Both evaluations reported 1,564 archived player
  forecasts and no stale/missing-input capture blocks. This is an archive
  count, not 1,564 independent validated outcomes.

## Evidence limits, not completed validation

No full-lineup model is promoted. Lineup experiment forecasts remain zero
while required starter distributions/availability are incomplete. A single
completed week does not satisfy an eight-week history threshold. Missing
unrostered-player results, specialist/rookie history and prospective outcomes
remain explicit. Joint historical residuals are not a validated model of
current opponent correlations. No lineup, waiver or trade was submitted.
