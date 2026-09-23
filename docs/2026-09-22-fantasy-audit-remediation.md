# FF-01–FF-05 implementation, first verified increment

## Delivered

- FF-01: recommendations, matchup and advice now use the same decision
  builder as the model page. Removed duplicate endpoint probability/point
  calculations and missing-as-zero matchup totals. Trade-specific research
  remains separate; the unused legacy helper is not yet removed.
- FF-02: deterministic empirical-residual simulations compare current,
  expected-points and one-player-alternative legal lineups against the
  actual opponent. Point ranges, estimated win/tie probabilities and
  candidate deltas are explicitly unvalidated research. No starter changes.
- FF-03: fresh provider estimates and unpriced roster context remain visible
  instead of an empty screen. Unknown projections remain null end-to-end.
  The `ranked_only` fallback label does not imply a fabricated expert ranking;
  unpriced players are ordered by name. A validated modelled tier is not yet
  available, and stale full-week values never become remaining-points advice.
- FF-04: choose a matched matchup/projection week anchored to upcoming NFL
  fixtures; collect next-week Sleeper pairs while retaining current records.
  A lone future projection cannot borrow last week's opponent. Matchup
  eligibility depends on its own players, not unrelated started NFL games.
- FF-05: complete league-scored history now supplies empirical distributions.
  Player diagnostics expose eligible history, complete games, missing scoring
  categories/counts, exact identity and supported position. No inferred zero
  stats, cross-player name matches or relaxed history threshold.

## Live verification

2016 Warriors: week 3 / planning week 3, fresh inputs and open decision
window. 266 players, 246 provider estimates, 20 unpriced; 187 complete-history
candidates, 31 insufficient-history and 48 unresolved/unsupported.
ESPN league: week 3 aligned, 286 provider estimates; 203 complete-history
candidates, 30 insufficient-history and 53 unresolved/unsupported.

These are the scoped roster-plus-60-free-agent pools, not the full league
catalog used in the independent audit. Their percentages are not directly
comparable. Both full-lineup simulations still withhold on incomplete
distribution/availability coverage.

## Still open

No claim that all five findings are fully closed. Needed next: independently
validated K/DST/rookie distributions and missing-category history repair;
correlated teammate/opponent scoring; prospective calibration of lineup win
probabilities; broader constrained lineup search; lock-preserving in-slate
optimization and next-week ESPN collection. Global slate lock still protects
waiver/lineup changes. Provider estimates are a fallback, not model promotion.

Validation: 645 tests passed, one skipped, 20 live tests deselected;
dashboard production build and TypeScript passed.
