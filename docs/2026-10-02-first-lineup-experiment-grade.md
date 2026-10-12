# First frozen lineup experiment grade

Week-three frozen simulation was blocked by missing BAL and GB defense totals. Scoring rules matched the official final snapshot. Added a grading-copy-only recovery using existing reconciled Sleeper components: exact frozen game membership, scoring hash parity, finality and same-position reconciliation remain mandatory. Frozen lineups, forecasts and official snapshots are unchanged. Each recovered value records source, observation time and reconciliation sample count.

Live recovery found BAL 2.0 and GB -2.0, with 12 same-position reconciliation checks. The experiment now grades. Current-lineup Brier 0.1586030625; candidate 0.14478025; coinflip 0.25. This is ONE observation under an older recipe, not evidence of calibration, general superiority or eligibility for promotion. Two week-four experiments remain pending; serving_promoted remains false.

Seventeen related tests passed before the additional direct recovery regression; the final focused recovery/validation run passed 13 tests. Production build passed, workers were idle before deployment, and live regrading verified source-bound recovery with no remaining blockers for this experiment.
