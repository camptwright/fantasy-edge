# Fantasy remaining-feature acceptance plan

## Delivered building blocks

League-scored weekly provider projections; lock-preserving lineup scenarios;
waiver alternatives and explicit retention warnings; player evidence; trade
package/roster-impact research; immutable prospective captures and grading;
owner-confirmed keeper eligibility and draft-cost API.

This sweep adds manual keeper review under My team, a server-side authenticated
proxy, unknown-by-default evidence fields, result invalidation on edits, and
league scoping. It does not save keeper selections or claim draft verification.
36 frontend tests, TypeScript and lint pass.

## Remaining implementation, in order

Retention follow-up: a live read confirmed stored projection snapshots reach
Week 6 only for all three configured NFL leagues. Full-season weekly inputs are
not available in that store. Added `retention_research.grade_frozen`: grades
saved before/after lineups against explicit final, game/league/scoring-bound
outcomes; rejects post-kickoff capture, missing points and duplicate weeks;
never hindsight-optimizes. Frozen evidence survives a JSON archive round trip.
20 retention/keeper tests pass. This offline evaluator is not scheduled,
connected to capture, deployed to serving or promoted. Forecast provenance,
future-week collection and evaluation integration remain required.

Follow-up: preview keeper UI now loads archived history through an authenticated
server proxy, displays draft season/ID/archive timestamp, preserves unknown keeper
flags, and clears all entered evidence on player changes. 36 frontend tests,
TypeScript, lint and production build passed; preview dashboard deployed.
Added offline `retention_research.compare` with explicit per-week full-scoring
inputs, verified bye exclusions and reoptimized roster scenarios. Its two tests
cover a weekly gain that destroys future QB coverage and missing-week withholding.
This research helper is not connected to a future-projection feed or serving;
keeper surplus valuation and specialist ROS implementation remain open.

October 9 update: scheduled daily exact-draft collection and read-only player
history endpoint implemented and deployed to worker/API/preview API. Live archive
contains 180 validated picks. All 180 `is_keeper` values are null; these cannot
establish prior keeper eligibility. 72 targeted tests pass, including the live-
discovered string archive-path regression. Current roster binding is explicit,
but same roster does not prove continuous ownership. UI auto-fill and verified
prior-keeper evidence remain open. Provider contract: https://docs.sleeper.com/

1. **Verified keeper history:** archive completed platform drafts/picks with
   league, season, roster and player IDs; retain raw provenance. Bind to the
   current roster and explicit previous-season keeper designations. Missing
   flags are unknown, never false. Test transferred players, ambiguous draft
   picks, undrafted players and first-round exclusions. Acceptance: a displayed
   draft round links to an archived record, and known ineligible players fail.
2. **Keeper value:** estimate next-season player value versus the forfeited pick
   under identical scoring, roster and season units. Do not subtract round
   numbers from fantasy points. Require next-season ADP/pick evidence and
   temporal holdouts. Test second-round-to-first cost and one-keeper selection.
3. **Retention model:** evaluate keep-roster versus each legal add/drop scenario
   across future scheduled weeks, respecting byes, position depth and scoring.
   Missing projections stay missing. Compare against current weekly-only
   baseline out of sample; do not promote based on examples or in-sample fit.
4. **Specialists:** reconcile DST points-allowed/returns, build verified rookie
   cohorts and prior-only opportunity features, and evaluate full-scoring K/DST/
   rookie outcomes. Existing kicker recency candidate lost its holdout; retain
   baseline. Per-game component evaluation is not full ROS qualification.
5. **Result completeness:** obtain exact athlete/event participation evidence
   for the 112 boxscore-absent player-games. Neither roster presence nor boxscore
   absence proves a zero. Preserve original captures and correction provenance.
6. **Prospective qualification:** collect future outcomes for each actual model
   version, report independent slate counts and missingness, and apply the
   promotion gate. Older-version outcomes must not qualify a changed recipe.
7. **Acceptance:** multi-league browser workflows, error/stale states, mobile and
   keyboard checks; matched deployed artifacts; no platform transaction side
   effects; documentation must distinguish engineering from model qualification.

## Unspecified rules

Owner clarification is still required for undrafted-player keeper cost,
transferred-player cost basis and forfeited-pick unavailability. These do not
block evaluating a directly drafted player with complete supplied evidence.

The entire fantasy area is not complete. Automatic keeper history, retention
modeling and specialist work are genuine implementation gaps, not merely waits
for user input or future outcomes. The broad UI redesign remains separate.
