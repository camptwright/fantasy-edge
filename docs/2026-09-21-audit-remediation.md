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

## Still open

The full suite is not certified green. A broader run was interrupted after
262 passes and 22 failures; 18 were API tests missing auth (subsequently addressed)
and four were distribution-override expectations requiring investigation.
The parlay contract test now explicitly expects rejection of unvalidated signals.

Next: finish suite isolation/override cases, deterministic numerical narratives
(B-05), persist version-bound promotion evidence, and prop/game linkage. Paper
logging, sharp-market reference pricing, distribution/ROS models and retention
remain later audit work. Published benchmark comparisons and the audit's model
promotion recommendation are not sufficient evidence to bypass the real gate.
