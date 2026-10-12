# Lineup cohort accounting

Added lineup experiment evidence_status reporting: all experiment statuses, current-source-version statuses, unique matchup slates, and unique graded matchup slates. Keys include frozen game IDs to avoid conflating seasons. Nested simulation grading failures take precedence over a successful outer weekly-margin grade. Older recipe grades never count as current-recipe evidence.

Fourteen focused tests passed. Backend builds passed and were deployed after idle-worker checks. No archived forecasts were modified or pooled, and no model was promoted.

Known limitation: current recipe identity includes orchestration source, so reporting changes also produce a new version. A future versioning refinement should separate prediction and evaluation identities with an explicit migration, without retroactively claiming equivalence between existing versions. Until then, version separation is intentionally conservative.
