# Player-prop evidence and linkage remediation

## Finding

Large reported edges were arithmetic from the all-history Normal baseline,
not evidence of profitability or a validated current role. A production read
found Terrance Ferguson's receptions history contained 14 games, mean 0.8571,
population standard deviation 0.9147. Darnell Mooney had 16 games, mean 2.125;
Theo Johnson had 16 games, mean 2.875. All three canonical records lacked a
current team. No roster assignment was guessed or backfilled from a betting
offer. Historical role averages alone do not establish upcoming participation.

NFL prop prospective cohorts inspected on September 21 contained at most 16
independent games each. Their existing review gates did not pass: insufficient
independent games, open evaluation windows, and baseline/market comparisons
were among the blockers. Multiple version cohorts are not additive evidence.

## Implemented

- Quotes expose model and cohort fingerprints, validation evidence, research
  EV separately from actionable EV, and explicit recommendation blockers.
  Unapproved props cannot enter live/best feeds, deterministic recommendations
  or parlays. Probabilities and pinned experimental parameters remain research
  outputs; no model promotion or artificial probability cap was applied.
- Approval requires a fresh grading report (at most two hours old), an exact
  cohort match, a closed prospective window, at least 200 independent games,
  a passing existing review with no blockers, and explicit approval matching
  model, cohort, sport, market and decision-evidence SHA-256. Configured
  approvals are empty. Unchanged regrading preserves the decision fingerprint;
  corrections or changed decision evidence invalidate approval. The source
  report's byte hash is also exposed for audit.
- Conservative review holds apply above 20% modeled EV or a 20-percentage-point
  model/fair-market gap. These are risk-screen thresholds, not statistical
  proof that smaller edges are valid. Even an approved model cannot bypass
  these holds. Integer-line props remain research-only because the current
  binary Normal baseline does not model push probability and exact EV.
- SGO, ParlayAPI and The Odds API prop event joins now require a unique exact
  matchup/kickoff, not the shared 24-hour team-pair fallback. Ambiguous or
  changed kickoff matches are parked. Team-market ingestion is unchanged.
- Migration 0018 adds nullable JSONB event binding to quote liveness metadata.
  Exact collectors populate it only after provider event resolution. Binding
  compares game UUID, sport, both teams and kickoff at serving time. Old quotes
  are not retroactively verified. Unknown/mismatched player teams remain held.
  This corroborates a matchup, not a confirmed lineup or future role.
- Cross-sport game history is excluded from projections and history features.
- Research capture remains independent of promotion, avoiding a circular gate.
  Unverified links can be archived for investigation, but cannot satisfy
  prospective protocol verification. Legacy archives keep their old identities.
- `/props/validation` and the dashboard's `/calibration/props` show blockers,
  fingerprints and bounded history diagnostics for the 40 largest current
  research estimates. Best Bets links to this page instead of implying that
  an empty actionable feed means ingestion failed.

## Verification and limitations

Full default suite: 632 passed, one intentional skip, 20 live checks excluded.
TypeScript checking and production dashboard build passed. Migration 0018 was
applied to both the isolated test PostgreSQL and production PostgreSQL.
Tests cover exact/adjacent/duplicate events, persisted bindings, changed kickoff,
missing/failed/stale/mismatched approval, large edges, integer pushes, cross-sport
history, and continued research capture while recommendation approval is held.

No evidence was invented and no current NFL prop model was declared validated.
The existing fixed 30-day evaluation window plus 200-independent-game threshold
is particularly restrictive for NFL; a separately preregistered season-aware
evaluation protocol is needed rather than silently lowering thresholds or
combining incompatible historical versions. Fresh roster/participation evidence
and prospective results remain data prerequisites. Old collectors that do not
write exact bindings remain research-only. Settlement-specific grading and
profitability are not established by these statistical summaries.

Approval file: `config/prop_validation_approvals.json`. An eventual reviewed entry
must contain `approved: true`, `sport`, canonical `market`, `model_version`,
`cohort_version`, and `decision_sha256` from the exact reviewed scorecard via
`prop_validation.decision_digest`. Editing this file cannot bypass a failed or
stale scorecard, missing event evidence, or the large-edge/push holds. There is
no automatic approval writer.

Initial deployed audit: 83 fresh NFL quotes, zero actionable; all 83 lacked
canonical player-team corroboration and pre-migration event bindings. Thirty-nine
triggered the large-edge hold. Provider polling can establish new exact event
bindings, but does not by itself establish the player's current roster/role or
pass model validation. No additional paid provider calls were forced.

Post-deployment smoke checks: recommendation generation and research capture
each succeeded twice in one worker process. Each capture archived 430 records;
recommendations correctly returned the no-qualified-quotes message. Both
`/calibration/props` and `/best-bets` on localhost:13000 returned HTTP 200.
