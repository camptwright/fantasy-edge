# Result hardening: September 10 deployment

## Implemented

- NBA and NHL now use the shared ResultSyncState retry cursor rather than treating
  an old successful ingestion marker as permanent. Recent successes refresh every
  six hours, older successes weekly; partial/deferred/confirming observations retry
  hourly. Corrections retain the two-observation, 30-minute minimum confirmation.
- Existing completed-game, identity and participation checks remain. NHL full-name
  identity lookup occurs inside the per-game savepoint and uses a player advisory
  lock. Missing fields do not delete facts or create zero outcomes.
- ESPN/MLB/NHL score writers serialize per sport. Changed final scores trigger a
  chronological replay using existing Elo/scoring-average functions, not a second
  incremental application. Before/after ratings are retained in ingestion_runs.
  Incomplete final history defers the replay, preserves ratings and retries hourly.
- MLB Cancelled games are no longer classified as played finals just because the
  upstream abstractGameState says Final. Thirteen exact historical cancellations
  were verified against MLB, archived, and corrected; the blocked MLB replay then
  succeeded for all 30 teams. Existing forecast archives were not rewritten.
- Authenticated `/calibration/result-completeness?sport=nfl&offset=0` reports unique
  stored player/game/stat expectations from the last 14 days. Follow next_offset
  when non-null (5,000-row page); do not interpret one page as the whole database.
  States distinguish present, missing_stat, participation_unconfirmed and
  pending_correction. This is quote coverage, not a complete roster assertion.

## Verification

44 focused tests passed; three live tests were deselected. NBA/NHL each completed
two bounded production retry runs with no errors, unmapped players, or duplicate
writes. Official score syncs completed; API health returned 200. The completeness
endpoint initially returned in 0.16 seconds. Dashboard/remote-access configuration
was not modified or rebuilt.

## Findings still requiring model/data work

The dated NFL report contained 343 expectations: 82 present, 181 missing stat,
80 participation unconfirmed. NCAAF: 1,778 expectations, 984 present, 657 missing
stat, 137 participation unconfirmed. MLB pages contained 5,174 expectations:
4,022 present, 366 missing stat, 786 participation unconfirmed. These are point-in-
time counts and can change with grading windows and provider corrections.

Many football gaps are quarter/half, each-period thresholds, first/last scorer,
fantasy-scoring and comparative game-high markets—not interchangeable with a
full-game boxscore. Smaller gaps remain in rushing/receiving primitives and
complete-component composites. They must be inspected individually; absent
participation is not a proven zero or a sportsbook void. NBA/NHL had no recent
quoted final expectations in this report; successful historical retry tests do
not establish live-season prop coverage. No candidate parameters were promoted.

Team replay is based on stored complete final history and the retained starting
rating; it does not reconstruct unknown historical forecasts or independently
certify upstream scores. Applied player corrections retain their separate
confirmation policy. Replay audits provide traceability for rating changes.
