# Performance repair — September 9, 2026

Implemented:

- Live compact props endpoint filters latest quotes for confirmed availability,
  known future kickoff and real prices before projection. Legacy `/props` remains
  compatible; `/props/history` offers bounded diagnostic paging.
- Best Bets and Recommendations use compact live props. Cached narrative evidence
  validates only its referenced quote IDs; withdrawn replacements cannot resurrect
  older offers. Narrative generation and forecast capture use live eligibility.
- Projections process 24 players at a time without changing eligible-history math.
  Backtests use lightweight historical rows and player batches, then restore global
  chronological order before candidate train/test splitting.
- Evaluation has a dedicated single-process queue/worker, recycled after each task.
  Owned Redis leases renew every 30 seconds and expire after 300 seconds. Lease loss
  cancels evaluation. Attempts exceeding the worker deadline display as abandoned.
- Calibration requests run concurrently with 20-second timeouts and partial-data
  messages. Redis uses noeviction to protect broker messages and lock keys.
- PrizePicks scheduling is removed under AGENTS.md policy; queued legacy tasks no-op.
- NFL Odds API status distinguishes the two-hour collection window without spending
  provider credits. All-history baseline wording replaces misleading rolling-window wording.
- Authenticated `/operations/performance` exposes bounded per-process p50/p95,
  payload sizes, server errors and peak RSS, without query strings or identifiers.

## Local deployment

Build with both Compose files, then update api, worker, evaluation, beat, dashboard
and redis. The Mac's localhost:13000 is a separate preview container, not the Compose
dashboard. Run `python scripts/deploy_local_preview.py` after building/updating
dashboard; it verifies the known target, retains the prior container, checks readiness
and rolls back on failure. It does not print inherited environment credentials.

## Observed checks

On the initial deployed repair: Best Bets 0.18s, Recommendations 0.10s, Calibration
0.48s, all HTTP 200. These are point measurements, not load-test percentiles.
Evaluation completed at 2026-09-09T17:04:42Z; a second invocation returned
already_completed_today. Evaluation cgroup peak was 207106048 bytes with zero OOM
events. Model candidates remain experimental; this repair does not promote them.

No actionable NFL/MLB/NCAAF player props were present during the live check. Speed
does not establish prop availability, prediction accuracy, or profitability.
Retained historical missing-result and invalid-timing exclusions remain real data
limitations. Do not repair them by inventing results or pregame timestamps.

## Remaining validation

Measure performance during an active priced slate and simultaneous browsing. The
legacy full-history `/props` endpoint remains expensive by design for compatibility;
move external consumers to bounded/live endpoints before changing its contract.
Automatic completion should be verified on subsequent days, not inferred solely
from today's successful run. No speculative indexes or correction-unsafe model
caches were introduced.
