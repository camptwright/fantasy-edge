# Player-result repair

NFL, NCAAF, and MLB scheduled result jobs use `result_sync_states` rather than
permanent per-event success markers. Each bounded batch reserves a quarter of
its capacity for older finals; remaining capacity goes to the last 14 days.
Unattempted games precede the least recently attempted eligible games. Unknown
kickoff times are recorded as deferred, not silently discarded.

- Failed, partial-identity, and pending-correction observations retry after one hour.
- Successful recent games are revisited after six hours; older games after seven days.
- Per-game row locks and a due-time recheck serialize concurrent repaired writers.
- Each observation uses a savepoint. Invalid payloads roll back their entire
  observation and do not prevent the next game from being processed.
- ESPN checks event ID and completed status. MLB checks its official schedule
  for the requested final game before reading its boxscore.
- Player identity must match the provider's existing crosswalk. Missing identities
  remain visible as partial runs and can resolve on a later attempt.
- Missing fields/players are not zeros, voids, or deletions. Play-order and other
  unsupported markets remain unsupported.

## Corrections

`result_corrections` retains the old and proposed values, provider/event identity,
first/last observation times, first/last payload SHA-256 hashes, status, and applied
time. A changed value must be observed in two successful provider fetches at least
30 minutes apart. A reverted or changed proposal supersedes the pending entry and
starts confirmation again. Correction and audit changes commit atomically.
Applied and superseded entries are retained. Hashes identify observations; they
are not full raw-response archives or cryptographic proof of provider authorship.

Pending corrections are excluded from new prospective grading reports as
`needs_review`. The grading job rebuilds reports from current facts, so applied
corrections flow into subsequent scores without rewriting saved forecasts or
old grading archives. Existing model promotion gates remain unchanged.

Read-only telemetry: `GET /calibration/result-repair`. The report includes tracked
game statuses, due tracked games, correction counts, and 50 latest ledger entries.
Counts do not include unattempted games. Details for individual retry attempts
are retained in `ingestion_runs` under `{sport}_result_repair`.

## Boundaries

This repair path covers player statistics for provider-linked finals. It does not
create missing historical event crosswalks, infer participation, apply sportsbook
settlement rules, repair team-score/rating history, or change NBA/NHL ingestion.
Legacy historical imports remain insert-only. Pending corrections retain the
current fact for existing projection consumers until confirmation; prospective
grading explicitly holds those outcomes out during review.
