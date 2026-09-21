# Shared player inputs — first implementation

Fantasy recommendations, matchup and trade inputs now use exact platform IDs via `player_identity.resolve_platform_players`, shared with the NFL roster lab. Sleeper IDs resolve through the published crosswalk to GSIS/ESPN; ESPN IDs use the sport-scoped external-ID table. Conflicting resolutions and unsupported platforms remain unresolved. No display-name fallback.

The Fantasy 2025-average proxy retains its original recipe but now uses final, known-time, non-preseason NFL games and excludes the whole player-game when a correction is pending. Missing weighted scoring components return no estimate rather than zero. Legacy name-based helpers remain available for offline comparison, but are no longer called by the API. Provider projections and serving betting coefficients are unchanged.

`GET /experiments/missing-results` exposes a read-only, deduplicated NFL player-lab work queue. It distinguishes missing games, missing player results, missing stat categories and pending corrections; it exposes the existing result-sync state and next retry timestamp. Scheduled games are not missing-result work. Original forecasts are unchanged, and the endpoint cannot approve corrections or force retries. Experimental displays the queue.

Verified: 12 focused unit tests, successful dashboard production build, and HTTP 200 on recommendations, matchup, roster lab and queue. Initial queue: 31 missing-player-result outcomes. This is not a DNP determination.

Remaining: shared CFB roster identity integration; consolidate all historical eligibility predicates; extend the queue to production betting and college forecasts; persist richer reason/action history; add a bounded authorized retry action and provider participation evidence. This phase does not make those broader queues complete.

## Cross-sport follow-up

CFB roster resolution now uses the same sport/provider-scoped identity service. Production player and team forecast archives join the NFL lab in the read-only queue, including CFB, MLB and other stored sports. Canonical stat aliases deduplicate equivalent outcomes. The queue distinguishes invalid capture timing and non-final event review from missing results; these cannot be repaired by inventing outcomes. Existing sport-specific retry state is displayed, not overridden.

The full queue moved to `/experimental/results` to avoid adding its archive scan to every Experimental page request. Archive loading runs outside the API event loop. Counts cover all selected archives; displayed items are capped at 200. Initial check: 998 outcomes (613 missing-player, 38 missing-stat, 347 invalid-timing). This is not evidence of 998 failed bets.

College lab historical reports are deliberately not treated as pregame forecasts. Automated college prospective capture is still outstanding; CFB production forecasts are included now. No settlement, correction approvals, frozen predictions, or betting coefficients changed. Shared identity was verified across all 67 Power Four schools; focused tests passed 23 cases.
