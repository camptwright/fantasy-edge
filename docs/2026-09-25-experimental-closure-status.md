# X-01–X-03 closure status — September 25, 2026

**September 25 policy correction:** the January 30, 2027 calendar gate described
below is superseded for the NFL lab. Qualification now uses the first 200 unique,
complete-pair, non-push prospective games in capture order, followed by seven
days after their latest kickoff for grading. No fixed approval date is asserted
before that cohort exists. The 200-game threshold, paired score improvements,
uncertainty tests, complete results and explicit promotion approval remain.
Later winning games cannot replace missing results or losses. Interim progress
and diagnostics remain available now, in September 2026. Other sports' protocols
are unchanged. Original captures are preserved under their old protocol versions.

The user has explicitly deferred off-host backup work; it is not a current blocker
or a completed protection measure. No additional backup work is being scheduled.

Live verification after the policy correction: current research version
`4664732de2c2ccfe85518e8877f32db4952006a282619e88f5a2835048d904e9`;
14 frozen forecasts, eight complete-pair captures selected, 192 further distinct
game captures needed. No approval date is asserted (`decision_not_before=null`).
Second execution created no duplicates, the governance endpoint returned 200,
and serving remained on the retained baseline. 682 full backend tests passed,
plus eight focused final-policy tests. Earlier version counts and the historical
January deadline below are superseded, not relabeled as current evidence.

Supersedes the remaining-work checklist in the September 23 progress report.
Not all findings can truthfully be marked closed yet.

## X-01: promotion/rollback implementation complete; candidate not approved

- Migration 0023 adds an append-only operator deployment log.
- Explicit promotion requires a current executable artifact, identical durable
  artifact payload, a fresh version-bound review, the actual retained serving
  baseline comparator, a closed evaluation window and at least 200 independent
  games passing the existing prospective/market checks. No override switch.
- NFL moneyline signals consult the approved selection. Other sports, spreads
  and totals are unchanged. The unblended lab is the only supported candidate;
  the market blend remains research-only.
- Serving rechecks the version and latest review. Missing, stale, failed or
  mismatched evidence falls back to the retained baseline. A separate operator
  rollback restores the baseline without needing a passing review.
- Prospective captures of promoted forecasts retain their own artifact cohort;
  they cannot silently mix with baseline forecasts.

Operator commands, inside the configured backend environment:

```
python -m scripts.model_deployment promote --version EXACT_VERSION --actor OPERATOR --reason REVIEW_REASON
python -m scripts.model_deployment rollback --actor OPERATOR --reason ROLLBACK_REASON
```

Promotion refreshes the evidence first and rejects insufficient qualification.
These commands were NOT used to promote a live model. Positive promotion and
rollback scenarios were exercised against synthetic evidence in the isolated
test database. Live selection remains `retained_baseline`.

## X-02: performance qualification remains OPEN

The old lab Elo comparator was not guaranteed to match the serving baseline.
New captures freeze the actual pregame serving Elo probability. Qualification
also requires a contemporaneous sharp-market reference. Incomplete captures
remain preserved but excluded by an outcome-independent eligibility rule.

The corrected protocol is version-bound and starts a fresh cohort, not a rewrite
of earlier captures. Final active research version:
`072297644eb3fde0f8b1d6f3706489419d346063bf3b955de186eba10ff5cb31`.

Live verification: 14 new forecasts, 11 complete paired observations and three
unpaired observations excluded. Second run captured zero duplicates. No graded
prospective games yet. Under the existing NFL 120-day collection plus seven-day
grading policy, decision is **not before January 30, 2027 UTC**. Passing remains
conditional on sample size and actual performance; the date is not a promised
approval. The market blend is compared with both the retained baseline and the
unblended lab. No claim of market superiority or profitability is warranted.

## X-03: local durability/recovery complete; off-host protection pending

- General forecast and grading evidence is database-backed and hash-checked.
- Shadow entries and closes now persist in the same durable store. Closing
  capture reads database entries even when entry files are missing. Imported
  4,202 historical entries and 142 closes; these remain non-actionable proxies,
  with no fabricated verified CLV.
- Daily retention now executes bounded, lossless gzip compression for eligible
  redundant result observations at least 90 days old. Latest sync evidence,
  correction hashes and unresolved games remain protected. Recovery bytes are
  hash-verified before replacing the original JSON, and paths/changes are checked.
  Two live runs found zero eligible files: no live originals were removed.
- A full PostgreSQL custom-format backup was restored to a NEW isolated database,
  `fantasy_edge_restore_20260925_audit`. Restored schema was 0023. All 1,681 forecast
  and 914 grading objects in that point-in-time backup passed content hashes.
- Local recovery file (temporary staging, not durable off-host retention):
  `/private/tmp/fantasy-recovery-20260925.BMAzEG/fantasy-edge.dump`, about 416 MiB.
  SHA-256: `41d09aa562853e53a19e686a1d3d6d5e12d80076484d03a31516559ccb1af979`.
  Both the staged file and isolated restored database were retained.
- This verifies local database recovery, not loss of the entire Mac mini.
  The user has been asked for a NAS or other authorized off-host destination.
  Scheduled off-host transfer and destination restore verification remain open.

## Verification

678 full backend tests passed, one skipped, 20 deselected. Subsequent comparator
and protocol refinements passed focused tests. All four backend services rebuilt
and recreated with migration applied to both isolated and live PostgreSQL.
Repeated live registry/shadow/retention calls used fresh worker loops. No model
promotion, destructive archive cleanup, or paid-provider quota bypass occurred.

Remaining external dependencies: prospective outcomes and an authorized durable
off-host backup destination. Do not close those by relabeling research evidence
or treating a local temporary backup as disaster protection.
