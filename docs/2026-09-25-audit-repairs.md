# September 25 full-stack audit repair status

Implemented and deployed September 25, 2026, approximately 21:56 UTC.
This is a progress/verification record, **not a declaration that every audit item is closed**.

## Deployed repairs

1. **Forecast persistence:** read-only repeatable-read capture now closes before a separate worker-owned write session persists the immutable forecast. Two actual task invocations on the final deployment each captured 498 records and reached paper/period steps. A dedicated isolated-PostgreSQL regression invokes the scheduled task twice on separate event loops. Production capture freshness has a durable marker committed with the forecast; calibration shows it independently of grading freshness.
2. **Catalog memory protection:** player-values retains all league rosters/top replacement candidates but pages additional catalog players (default 50, maximum 100). Trade impact explicitly loads requested participants and adjustments, not the entire catalog. Historical facts stream narrow scalar columns rather than materializing full stat/game ORM objects. Replacement baselines do not change with catalog pagination. The compact UI response omits bulky distributions without deleting detailed API evidence.
3. **Shared in-flight fantasy calculation:** concurrent requests for the same inputs share one calculation. Different calculations are serialized with a bounded pending set; overload returns 503 with Retry-After. Generation owns its session, so one disconnected caller cannot close another caller's session. Returned objects are independent copies, and completed decisions are not cached across later requests. This is not yet a persistent background fantasy read-model service.
4. **Missing-result request path:** the API serves a durable, timestamped diagnostic snapshot with paging, pending/stale states, and aggregate counts. A separate evaluation-queue task rebuilds it. Production forecasts come from verified database archives, not raw-file reparsing. Correction disputes are keyed to game/player/stat rather than all stats for a player. Live snapshot: 1,975 unresolved outcomes; no missing fact was fabricated or silently resolved.
5. **Archive indexing and worker isolation:** imports record verified file metadata/content hashes in a durable index and skip unchanged files whose digest remains stored. Changed files are rehashed; independently stored forecast evidence still undergoes integrity verification. Grading and missing-result rebuilds run on the dedicated evaluation queue. Warm import measured 0.132 seconds with zero pending files. First post-deployment grading completed successfully in 56.4 seconds; full-cohort grading is still a remaining optimization.
6. **Payloads and UI:** experimental labs load individually; calibration uses a compact paginated report contract; missing results expose page navigation and stale/pending warnings; player-values sends a compact UI contract. The detailed default calibration API remains available for compatibility. Fantasy server fetch helpers have bounded timeouts and catch transport/body errors.
7. **Fantasy consistency:** the routed Trade page now uses the same Player Values/roster-impact model, including explicit uneven-trade add/drop plans. The legacy component/API contracts are retained for compatibility, not promoted as the canonical UI. Exact schedule-linked opponent names are exposed. Recent name-matched headline context is loaded for recommendation roster/waiver players, never treated as structured injury confirmation or a numeric adjustment.
8. **Version evidence:** daily completion is insufficient unless the report's model/policy/cohort versions match current serving versions. A change during evaluation makes the report partial. The final deployment ran a fresh complete evaluation at 21:56:35 UTC and reports version compatibility. Fantasy now exposes its prospective recipe digest alongside the readable model label. **Audit clarification:** fantasy prospective capture already had a source-code digest; the missing piece was its visibility in the serving response, not absence of all code-bound fantasy evidence.
9. **Remote auth:** remote JWKS objects are reused for the configured team, preserving fail-closed JWT checks and adding explicit issuer matching. Local preview checks remain unchanged. Authenticated remote latency was not measured.

## Measured verification

Single requests, not load-test percentiles; body sizes are not compressed-wire claims.

| Measurement | Audit | Repaired deployment |
|---|---:|---:|
| Fantasy page total | 4.519 s | 1.981 s |
| Experimental HTML | 1,232,864 bytes | 154,715 bytes |
| Calibration HTML | 1,327,398 bytes | 173,101 bytes |
| Calibration API, UI contract | 2,548,453 bytes | 21,219 bytes |
| Populated missing-result API | 17.822 s | 0.069 s |
| Player-values | API OOM during unbounded request | 315 players, 1.714 s, 216,647-byte compact response |
| Concurrent recommendations / matchup | duplicate independent builds | 1.326 s / 1.270 s |

All inspected final pages returned HTTP 200. Calibration page server time remained about 1.65 seconds and needs further profiling. Trade now uses a richer model, so its approximately 1.63-second page time is not comparable to the former faster weekly-proxy page as an identical workload.

The API had zero restarts and OOM=false after repaired-request checks. At an intermediate post-repair snapshot it used approximately 128 MiB under the unchanged 768 MiB limit. This is not a peak-memory or long-duration stability certification.

Full isolated suite: **690 passed, 1 skipped, 20 deselected**. The deselected tests are explicitly marked live external-network tests. Final targeted checks after compact-response adjustments: **17 passed**. Dashboard production build/type checks passed; `git diff --check` passed. The live app and local preview were rebuilt/replaced; the prior stopped preview container was retained for rollback. No wagers or model promotions occurred.

## Remaining work — not closed

- Convert full-cohort grading and diagnostic snapshot rebuilding into truly incremental, correction-aware processing. Moving this work off HTTP/default ingestion queues does not remove all background scan cost.
- Persist background fantasy read models with precise roster/scoring/history/availability invalidation, and validate sustained/concurrent performance. Current single-flight protection is bounded request-time computation, not that larger architecture.
- Profile the remaining calibration page latency and selected college-lab payload; selecting one lab prevents loading every lab but does not paginate every lab internally.
- Add durable request/task metrics, restart/latency/freshness alerting, and a reproducible committed release manifest. The repository still contains pre-existing uncommitted governance/migration changes and this repair batch; no commit or push was performed in this pass.
- Provider budgets/windows still constrain fresh actionable props. Existing provider coverage/quota diagnostics show reservations versus reported balances; no paid upgrade, quota bypass, or weakened eligibility gate was introduced.
- Finish independent position-specific/lineup validation and missing player/stat history. Serving code changes cannot manufacture the required prospective outcomes.
- Verified CLV still requires official rule contracts, exact reviewed receipt/quote mappings, and official closing evidence. No verified sample was invented, and proxies remain proxies.
- Measure authenticated remote access and long-duration live stability. Local success is not proof of remote performance.

No new migration was required for this repair batch; durable summaries reuse the existing content-addressed evidence store. Existing earlier migrations and uncommitted edits were preserved. Off-host backup work remains deferred by user instruction.
