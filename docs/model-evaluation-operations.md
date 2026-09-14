# Versioning and daily evaluation

Version schema 2 hashes normalized Python ASTs, excluding comments, docstrings,
formatting, and unrelated API endpoints. Serving functions still embedded in
the sportsbook router are hashed conservatively as whole functions: changes
inside them may create a new version even if only presentation changes.
Active distribution parameters are fingerprinted rather than report metadata.
Moneyline serving parameters and enablement are retained in the manifest.

New forecast archives contain model_version, a separate policy_version inside
version_manifest, and a combined cohort_version. Grading groups new forecasts
by cohort_version so eligibility-policy changes are not silently pooled.
Legacy archives use their original model_version unchanged; no historic cohorts
are merged or retrospectively re-versioned. One transition to the new scheme
is expected. This is a single app-wide version, not yet per-sport/model-family.

Daily evaluation checks at minute 10 of each hour and on worker startup. A
complete report dated today in UTC suppresses duplicate work. Each sport has
its own read-only repeatable-read transaction and 120-second SQL statement
timeout; one sport's ordinary error does not discard another sport's results.
Complete reports publish atomically to calibration; partial reports publish
separately to evaluation-partial. Running/completed/failed attempts are recorded
under evaluation-runs. A hard-killed process may leave a running attempt; the
Redis lock expires after one hour, permitting the next catch-up check.

GET /calibration/evaluation-status exposes freshness, last attempt, last complete
report, today's completion, and current version manifests. Overdue or partial
evaluations are not advertised as success. No evaluation promotes a model.

Limits: this is one successful evaluation per UTC day, not a backfill of missed
historical daily snapshots. Readiness/insufficient-data findings are valid
evaluation results, not proof that every market is qualified or calibrated.
