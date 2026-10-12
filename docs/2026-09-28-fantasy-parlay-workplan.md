# Fantasy, navigation and parlay work — implementation plan

## Current evidence

The checked Sleeper league has current week-four inputs and a complete 272-game schedule, with 24 unknown future kickoff times explicitly retained. Of 269 players in the bounded decision pool, 243 have provider estimates, 13 have historical estimates and 13 remain ranked-only. Current matchup projections are 132.05 versus 126.68. A calibrated win probability is unavailable; this must not be replaced with an invented value. These counts are a snapshot, not coverage for every league or player.

## First implementation batch

- Fantasy subnavigation preserves the selected league query parameter.
- Consolidated duplicate trade links into Player values & trades; existing trade URLs remain compatible. No database tables were merged or dropped.
- Added navigation loading boundaries, providing immediate transition feedback without caching stale decisions or claiming faster underlying models.
- Existing manual parlay requests are bounded to one through eight legs. Prop lookup is restricted to requested IDs while retaining latest-quote selection and all actionability/same-event checks. Prop-only builds skip team-signal generation.

## Next implementation sequence

1. Audit every configured league and reconcile player and starter coverage. Distinguish provider projections, historical candidates, actual scores, started-game restrictions and unsupported inputs. Consolidate duplicated projection tables around one evidence-bearing row contract; preserve per-player provenance and availability labels.
2. Measure navigation in the browser, not just API response times. Check slow routes, payloads, full reloads, hydration and duplicate requests. Loading indicators are not proof that latency is solved.
3. Build a separate AI-assisted parlay workflow using the existing configured model gateway. AI may interpret requested sport/book/leg-count constraints and explain verified selections; it must not invent quote IDs, prices, probabilities, eligibility or statistical evidence.
4. Resolve selections server-side against current eligible quotes, require a consistent executable book, reject duplicates/contradictions/same-event combinations without a validated joint model, and disclose residual cross-game independence assumptions. Joint probability and EV remain deterministic research calculations, not verified sportsbook payouts or guaranteed profitability.
5. Bound model timeouts/concurrency, fail explicitly when AI is unavailable, validate structured output against an allow-list of eligible IDs, recheck quotes at final construction, and test stale/withdrawn quotes and fabricated outputs. No automatic wagers or model promotion.

## Follow-on: AI-assisted parlay lab implemented

Added `/parlays` and authenticated `/parlays/assist`, with a same-origin browser proxy that keeps API credentials server-side. Users choose sport, book, two–four legs and bounded preferences. AI selects only keys from at most 40 eligible positive-edge offers at that book; provider prefixes use the shared book-brand resolver. The validator rejects fabricated/duplicate IDs, malformed replies and repeated events. Calls have a 20-second timeout and one in-flight AI request per API process. Preferences are soft selection guidance, not a guaranteed hard filter.

The existing deterministic builder rechecks selected quote eligibility after AI latency. Missing final legs reject the whole assistant result. Joint probabilities retain the explicitly disclosed cross-game independence approximation; a result is `research_estimate`, `actionable=false`, `payout_verified=false`. There is no same-game correlation model, verified parlay payout, automatic wager or promotion.

The configured gateway passed a live synthetic two-offer allow-list test; synthetic data was not persisted as model evidence. Live NFL/DraftKings and browser-proxy tests exercised the insufficient-eligible-offers path. No research-only quotes were promoted to fill the list. Initial source verification found and corrected prefixed sportsbook names, with a dedicated regression.

Full suite before that final naming fix: **722 passed**, one skipped, 20 deselected. Final focused assistant tests: **6 passed**. Production backend/dashboard builds passed. Fantasy, Operations and the new Parlay lab returned HTTP 200. Frontend provenance matched 64 source files and 161 artifacts, build `UBgL0e7v90af4H1RlAbGz`. Previous preview retained as `fantasy-edge-grading-preview-before-20260929T023850788314`.

All three configured leagues returned week-four `candidate` decision reports with `pregame_candidate` matchups. Player tier counts: first Sleeper league 243 provider estimates / 13 historical estimates / 13 ranked-only; second Sleeper league 303 / 16 / 32; ESPN league 228 provider estimates. These are bounded decision pools, not proof that every player has a qualified historical model.

Broader fantasy coverage, numerical betting-model improvements, full browser lag profiling and deeper table consolidation remain in progress. The new workflow does not establish betting profitability or calibrated matchup probabilities. No paid-provider upgrade or eligibility override occurred.
