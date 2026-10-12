# Historical player-pool pacing repair

Found that fresh scored-history and matchup snapshots could suppress collection when the separate historical-player archive was absent. The daily skip now also requires a fresh player archive with matching scoring hash. Missing, malformed, stale or rule-mismatched pool snapshots no longer hide behind fresh roster snapshots. Existing complete-slate finality checks and daily pacing remain.

Nine focused tests passed, including missing-pool recovery. Backend images built and deployed after idle-worker checks. Two consecutive live ESPN sync invocations succeeded. Archives are now reconciled for weeks 1–3: 483, 483 and 486 accepted player scores respectively; 224, 226 and 228 matching roster scores, with no conflicts.

These counts describe result coverage, not new validated forecasts. Legacy captures without frozen official scoring-rule evidence remain excluded from the historical grading fallback. Sleeper missing-player coverage and calibrated matchup probabilities remain open.
