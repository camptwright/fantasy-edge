# Audit remediation checkpoint

The complete prior tree and the supplied audit were committed and pushed as
`96a7bdb` before beginning these repairs. The audit was read in full.

## Implemented and checked

- F-00/F-01: ESPN date ranges are expanded locally into single-date requests;
  repeated week-wide events are deduplicated. Each sport receives a separate
  database session and exceptions no longer abort the other sports. A deployed
  refresh completed for NFL/NCAAF/NBA with no failures. Upcoming database coverage
  included 217 NFL and 26 NCAAF games. Zero writes on a subsequent refresh means
  unchanged observations, not a failed fetch.
- F-02 diagnosis correction: latest-run failure detection already existed.
  Delivery was failing with HTTP 400, while the health task reported success.
  Alerts now have a UTF-8 byte bound and return delivery status; the health task
  fails visibly on delivery failure. The deployed health alert successfully sent
  with 383 issues summarized. Do not interpret zero deduplicated writes as an
  outage without observed-input coverage; no blanket zero-write alert was added.
- F-03: scheduled-score placeholders now become NULL. Legitimate live/final
  zero scores remain intact. Cleared 281 existing scheduled ESPN 0–0 placeholders.
- B-R2/B-02 safety containment: team signals default to research-only without
  version-bound validation. Positive EV, positive sizing, valid probabilities,
  future kickoff and fresh observations are explicit checks. Best Bets,
  recommendation inputs and suggested/custom parlays honor actionability.
  Live verification: 256 research signals, zero actionable; 219 nonpositive EV.
  No model promotion or odds calculation was changed. A proper persisted
  promotion/evaluation loader is still needed; legacy CalibrationReport has no
  model fingerprint and cannot authorize a different serving configuration.
  Team research forecasts remain capturable for evaluation.
- X-05 partial: migrated the isolated `fantasy_edge_test` database on port 5433
  through 0017, never production. Repaired the three reported stale fixtures,
  a test writing to the production archive path, and missing API-test auth.
  Combined targeted database/API regressions: 59 passed, one live test deselected.

## Test and narrative follow-up

- X-05: default suite now passes: **613 passed, 1 skipped, 20 live checks
  deselected**, in 29.79 seconds against the isolated PostgreSQL test database.
  The skip is the intentional relocation-era NFL team alias exception.
  Distribution/projection fixtures now have historical kickoff times; the
  schema checklist includes the six newer tables. Eligibility was not weakened.
- Full-season nflverse tests are explicitly marked live (all six passed in the
  earlier broad run). Player ingestion tests use fixed provider rows while
  exercising real database writes, identity ambiguity, game linkage and unique
  constraints. They no longer download whole seasons repeatedly. A DB advisory
  lock prevents overlapping test runs from truncating each other's fixtures.
  The earlier long run's StaleDataError followed overlapping focused/full runs;
  serial runs are green. Other excluded live checks were not certified here.
- B-05: numerical recommendation summaries no longer call an LLM. Each selected
  side uses its own probability and American price to compute break-even
  probability and EV with explicit units. Only actionable, positive-EV, finite
  priced quotes qualify; up to eight are ranked deterministically. Cached legacy
  prose is withheld. Cached deterministic numbers are recomputed against current
  quote evidence, so a changed probability invalidates text even if the quote ID
  is unchanged. Event-start and scoped-evidence regressions pass.
- TypeScript checking, dashboard production build and focused Python lint pass.
  API/worker/beat/dashboard and localhost preview were redeployed. Generation
  succeeded twice in the same worker process; live GET /recommendations returned
  HTTP 200 with deterministic, quote-bound summaries. No model was promoted.

## Still open

The player-prop follow-up is implemented in
[the dedicated remediation report](2026-09-21-player-prop-validation.md):
version-bound approval gates, exact provider-event bindings, research-only
large-edge holds, and a validation dashboard. No current prop model qualified
for approval. Roster/participation evidence, prospective validation and a
preregistered season-aware evaluation protocol remain substantive data/model
work; deterministic arithmetic does not establish profitability.

Next: collect corroborated player/roster evidence and prospective results. Paper
logging, sharp-market reference pricing, distribution/ROS models and retention
remain later audit work. Published benchmark comparisons and the audit's model
promotion recommendation are not sufficient evidence to bypass the real gate.
