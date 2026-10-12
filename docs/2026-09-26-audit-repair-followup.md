# Audit repair follow-up — September 26, 2026 UTC

## Deployed and verified

- **Incremental forecast selection:** a derived checkpoint processes new archive rows, detects modified source rows through their PostgreSQL MVCC versions, and verifies content hashes. Late imports remain supported. Legacy/current selection-policy mixtures conservatively fall back to reference-order rebuilding. Current game results and pending corrections are still read every grading run; outcomes are not frozen in this cache.
- **Bounded checkpoint persistence:** frozen grading inputs are compacted, compressed, and stored atomically in approximately 1 MiB parts. Original forecast evidence remains unchanged. The root references integrity-checked parts. Decode/storage budgets reject oversized inputs. The deployed production checkpoint used ten parts, each with at most 1,048,576 bytes of compressed content plus small JSON metadata.
- **Background fantasy read models:** scheduled generation for all three NFL fantasy leagues, transactional source-write invalidation, code/config fingerprinting, two-minute maximum expiry, and earlier expiry at kickoff or source-staleness transitions. Arbitrary catalog/trade requests retain the bounded on-demand path. Expired or invalid snapshots fall back to fresh calculation; missing data is not promoted into eligibility. Concurrent refresh serialization conflicts retry on fresh sessions.
- **Durable operations history:** `/operations` shows persistent observations, slow-route/server-error warnings, production capture freshness, API process changes, and monitoring heartbeat age. Up to 288 five-minute observations survive API restarts. These are in-app alerts, not external notifications or proof of a specific OOM cause. Latency samples remain the API's rolling last 200 requests per route, not fixed five-minute windows.
- **Security dependency repair:** Next.js updated from 14.2.35 to 15.5.24 with matching lint configuration; patched PostCSS/nanoid and a compatible development js-yaml lockfile update. React remains on the existing compatible major. Production build succeeds; both production-only and full npm audits report zero known vulnerabilities at verification time. This is not a penetration-test certification.
- Migrations 0024 and 0025 were applied successfully to isolated PostgreSQL and production. Source invalidation triggers have a bounded migration lock wait. API, worker, evaluation worker, beat, dashboard, and local preview were rebuilt/replaced. A prior stopped local preview is retained for rollback.

## Measurements

| Check | Result |
|---|---|
| Cold checkpoint build plus grading | 35.362 seconds; 1,704 archives processed |
| Warm grading | **2.746 seconds**; zero archives processed, 1,704 reused |
| Outcomes across those two runs | Identical: 22,214 graded; 1,487 missing; 1,437 pending; 28 pushes; 1,159 invalid timing |
| Cached fantasy decision-model response | 0.363 seconds, HTTP 200, explicitly background-checkpoint-backed |
| Fantasy recommendations | 0.099 seconds, HTTP 200 |
| Durable operations history | 0.003 seconds, HTTP 200; history survived API replacements |
| Refresh worker | Two successive invocations refreshed all three leagues successfully |

These are individual measurements, not load-test percentiles. Cache misses and changed inputs still require calculation. Other sports updating shared input tables conservatively invalidate fantasy snapshots as well; cache-hit rate should be observed over time.

Full isolated suite: **699 passed, 1 skipped, 20 live-network tests deselected** before the final chunk-storage adjustment. Focused checkpoint/evidence tests after that adjustment: **9 passed**. Production builds and live route checks passed. Frozen model probabilities and actionability gates were not relaxed; no model promotion or wager execution occurred.

## Incident during verification

The first production-sized checkpoint attempt submitted roughly 90 MB of JSON, duplicated by the initial upsert binding. PostgreSQL hit its container memory limit, recovered its database processes, and temporarily dropped connections. This was caused by the new implementation, not an existing provider outage. The subsequent size guard refused the still-too-large compressed single-row form before writing. The final implementation uses compacted, compressed, atomic bounded parts and nonduplicated upsert bindings. Both cold and warm production grading then completed successfully, and database/API health checks passed. The historical Docker OOM flag can remain set after recovery; it is not evidence of a new incident.

An overlapping fantasy refresh also exposed a repeatable-read serialization conflict; fresh-session retries now handle that race. These failures are why the production-sized verification matters in addition to unit tests.

## Remaining limits

- Grading now avoids rescanning old forecast archives, but still rechecks current outcome facts across the selected cohort. Fully result-delta-based grading remains an optional further optimization, not a claim made by this implementation.
- Long-duration stability, cache-hit ratios, trigger contention under heavy ingestion, and authenticated remote latency still need accumulated observations. The monitoring collection is active; external alert delivery is not configured.
- Player/position/lineup qualification and prospective promotion require additional real evidence. Verified CLV still requires reviewed receipts, exact rule binding, and supported official closing-price evidence. None was fabricated.
- The repository still contains earlier uncommitted changes and these repairs. No commit/push was performed in this follow-up. Off-host backup work remains deferred by the user.
- Python runtime dependencies are now version-pinned as described below. Base-image, OS package, build-tool and artifact-hash pinning remain release-hardening work; this is not yet a fully reproducible build.

## September 26 evening follow-up

- Reviewed 209 persisted monitoring observations. The current heartbeat was healthy with no active alerts. Recorded history contained one API process-change notice and no slow-route/server-error alerts. This covers sampled observations and rolling request windows, not continuous load testing or proof that no failures occurred.
- Isolated the remaining calibration delay: live results 0.081 seconds; NCAAF readiness 1.494 seconds. A separate profile measured history aggregation at 0.170 seconds and evaluation of 4,601 quote records at 1.017 seconds. These are point measurements.
- Deployed independent server streaming for the NCAAF readiness panel. Live results and capture status no longer wait for that panel. Three post-deployment checks delivered live results in 0.378, 0.113 and 0.116 seconds; complete responses took 1.467, 1.091 and 0.985 seconds. Two before-deployment checks took 1.947 and 1.397 seconds before delivering any body. No evidence checks were removed or cached; unavailable readiness remains explicitly unavailable, not zero.
- Fantasy, Best Bets, Experimental and Operations returned HTTP 200 after deployment. The previous local dashboard container is retained as `fantasy-edge-grading-preview-before-20260926T200327990255` for rollback.
- Added `requirements-runtime.lock` from the existing deployed Python environment, including transitive versions. Docker installs the lock, constrains project installation against it, and runs `pip check`. A fresh API image built successfully and its dependency check passed. Existing backend containers already use these versions and were not restarted solely for this build-only change. Base/OS/build tools and package hashes are not pinned by this file; offline-model extras are outside this runtime lock.
- Added regression tests for chunk size, multi-part reconstruction, rollback preserving the prior checkpoint, and rejection of missing/tampered/rehashed parts. Added runtime-lock coverage/compatibility checks. The targeted lock/checkpoint/monitoring suite passed all 12 tests.
- Final full isolated regression suite: **705 passed, 1 skipped, 20 live-network tests deselected** in 39.98 seconds. Dashboard production build/type checks passed; `git diff --check` passed.
- No model promotion, changed eligibility threshold, fabricated settlement evidence, paid provider change, commit or push occurred in this follow-up.
