# Fantasy-first overhaul: implementation ledger

## Agreed direction

Personal Mac mini app; fantasy first, markets and research retained. Existing/free
providers only. Parallel replacement, decision-first UX, pregame models plus
live scores. No live probability claims without separate qualification.

## Baseline and first slice

Before changes, the release auditors matched all four backend services (246
source/config files plus pinned dependencies) and both dashboards (65 source
files, 161 sealed artifacts). Existing uncommitted work was preserved.

Implemented an additive `/workspace` preview with Today, Fantasy, Markets,
Research, and Settings. Fantasy views select actual NFL leagues and show compact
candidate lineups with unknowns, locked players, evidence IDs, and limitations.
The other workspaces organize links to existing tools; they are not rewritten
market, trade, or research engines. URLs preserve explicitly selected leagues.

New authenticated, no-store APIs:

- `GET /api/v2/fantasy/leagues`: compact league catalog.
- `GET /api/v2/fantasy/leagues/{league_id}/overview`: validated background
  checkpoint only; no build fallback, provider call, refresh dispatch, or write.
  Missing/invalidated/expired snapshots return `updating`, unknown leagues 404.
  `snapshot_available` is freshness, not model qualification. `actionable` is
  always false. The client hides lineup estimates after snapshot expiry.

Types are generated from the Pydantic serialization schemas using
`PYTHONPATH=. .venv/bin/python scripts/generate_workspace_types.py`; use
`--check` to detect drift. Legacy response shapes are unchanged.

The isolated preview API mounts only v2 reads, requires the existing token,
and uses a two-connection pool with database read-only transactions and a
two-second statement timeout. No scheduler or new polling is started.

## Deployment and rollback

Preview: `http://localhost:13001/workspace`. Existing app at port 13000 stays
unchanged. Deploy only with the explicit compose file:

```sh
docker --context colima compose -f docker-compose.workspace.yml up -d --build
```

The preview uses the existing `fantasy-edge_fantasy` network and database;
there are no schema changes, backfills, or copied production volumes. Port
13001 is bound to loopback and remote/Cloudflare requests are rejected by the
existing local-preview middleware. Legacy tools in the preview still call the
current API; v2 reads use `FANTASY_WORKSPACE_API_URL`.

Rollback is stopping the two preview services, not rolling back production:

```sh
docker --context colima compose -f docker-compose.workspace.yml stop
```

The repository now intentionally differs from the legacy release. Do not
deploy all uncommitted files indiscriminately merely to silence drift reports.
No commits/pushes, model promotions, or destructive cleanup are part of this slice.

## Verification

- Six offline backend tests: unknown/missing checkpoint behavior, zero versus
  unknown points, locks/evidence, authentication, absence of mutation routes,
  generated contract consistency.
- Sixteen dashboard Node tests, ESLint, TypeScript, and the final Docker
  production build passed, including expiry boundary/invalid timestamp tests.
- Live read smoke: all three leagues returned current snapshots, with 9/11/9
  candidate starter slots. League list 9 ms; nine sequential overview samples
  54–82 ms. These are API smoke samples, NOT load-test percentiles or UI timings.
- Browser verified real roster rendering and league switching; missing/locked
  starter projection remains Unknown rather than zero.
- Final HTTP smoke: existing app 200 (17 ms), workspace 200 (175 ms), Markets
  hub 200 (17 ms). Individual complete-response samples, not browser render or
  concurrent-load measurements. The original services were not restarted.

## Remaining work in order (not closed)

1. Foundation: per-domain invalidation instead of global revision churn;
   prediction-artifact identity separate from policy/release/reporting;
   comprehensive performance traces and correction/read-model regression tests.
2. Fantasy vertical: player profiles, useful action ranking/change explanations,
   matchup contributions, then waiver/trade/ROS workflows inside the new shell.
   The initial Today page is an overview, not the completed daily action brief.
3. Models: opportunity/availability distributions, correlated outcomes, explicit
   K/DST and rookie models; retain baselines and register prospective gates.
4. Markets: consistent book/line/rule comparisons, research/actionable separation,
   ledger integration, validated correlation handling for parlay research.
5. Cutover: mobile/desktop/accessibility and concurrency acceptance, per-feature
   flags and parity checks; only then replace legacy routes and remove duplicates.

Do not claim this first slice completes the overhaul or improves prediction
accuracy. It changes delivery and evidence presentation, not prediction math.

## Second slice: relevant-write invalidation (deployed)

Migration `0026_fantasy_invalidation` replaces unconditional statement triggers
with transition-table checks. Empty statements, identical updates/upserts, and
known non-NFL changes no longer invalidate NFL fantasy checkpoints. Both the old
and new rows are considered, so sport changes and crosswalk rebindings invalidate
the affected NFL domain. Stats and correction records follow their game; platform
rosters/snapshots follow their league. Missing parent/domain information fails
closed. TRUNCATE always invalidates. Full-row comparisons retain timestamp and
scoring JSON changes; freshness updates are not discarded as cosmetic changes.

The existing single revision and checkpoint format remain compatible. This is
sport/no-op isolation, NOT per-league isolation: an NFL source change still
invalidates all NFL league snapshots. No cached result is served past the existing
expiration or kickoff guards. Prediction math, source recipe files, and evidence
cohort identities were not changed.

Verification and rollout:

- Migration applied to real isolated PostgreSQL; downgrade to 0025 and re-upgrade
  passed. Eight new regression cases plus updated existing cache tests.
- Full non-live suite: **751 passed, 1 skipped, 20 live tests deselected**.
- Post-downgrade/re-upgrade checkpoint subset: **15 passed**. Ruff and diff checks
  passed. No schema-table additions or result-data rewrites.
- Applied live with a five-second DDL lock timeout using the new workspace image.
  Only the preview API was recreated; production app/workers were not restarted.
- All three leagues subsequently returned current checkpoints (9/11/9 slots).
  Nine overview smoke reads were 55–75 ms. Current app and workspace returned 200;
  the workspace complete-response sample was 79 ms. Not load-test percentiles.
- Existing API and new preview reported the identical fantasy recipe hash
  `28d3d5798840f5347df56c0c81a0be26b48b15b0232bdb5d8c5c9e70a99f926f`.

Live migration rollback, if needed, uses the image containing migration 0026:

```sh
docker --context colima compose -f docker-compose.workspace.yml run --rm --no-deps workspace-api alembic downgrade 0025_fantasy_input_revision
```

That restores the conservative invalidation behavior and bumps the revision
once. It does not remove source records or forecasts. Old production images do
not contain the new migration, so use the workspace image for migration commands
until the next coordinated production release.

Live smoke command (import path required):

```sh
docker --context colima compose -f docker-compose.workspace.yml exec -T -e PYTHONPATH=/app workspace-api python scripts/workspace_smoke.py
```

Next: league/domain revision vectors, followed by prediction-artifact identity
separated from grading/reporting changes. Do not relabel historical observations
as evidence for a newly defined artifact without explicit equivalence validation.

## Third slice: league-scoped preview validation — October 4 (deployed)

Migration `0027_fantasy_scope_revisions` adds two metadata tables: shared/league
revision counters and checkpoint-to-revision bindings. It extends the 0026
change/sport filters without changing their conservative global revision. League
source changes advance the old and new league scopes; shared NFL results,
corrections, identities, and truncations advance the shared scope.

An AFTER checkpoint-write trigger binds the unchanged payload digest to the
writer transaction's source revisions. It refuses a binding when the payload's
legacy revision does not match that source snapshot. Metadata is stored
separately: neither forecast payloads nor their original digests are rewritten.
Existing checkpoints remain unbound until normal scheduled refresh; the reader
uses the legacy global check in that interim, never inferred scoped evidence.

The new preview reader (`workspace_checkpoints`) reads the payload, its binding,
and current revisions in one SQL statement. It retains recipe/digest checks,
expiry, future-timestamp rejection, and the no-generation-on-GET boundary. It
does not change the legacy fantasy reader or model recipe identity. All three
live leagues have been observed using `league_and_shared_nfl` after the existing
worker's regular refresh. The worker and production API were not restarted.

Migration safety includes a five-second lock timeout, draining source writes
before trigger replacement, and a nonzero shared migration epoch. A writer whose
repeatable-read snapshot predates the migration cannot acquire current scope
evidence by treating missing counters as zero. No evidence was backfilled.

Verification:

- Real PostgreSQL downgrade/re-upgrade passed; focused suite **33 passed**.
- Final full non-live suite **762 passed, 1 skipped, 20 live tests deselected**.
- Tests cover other-league isolation, own/shared invalidation, league
  reassignment, rollback, unbound fallback, stale payload rejection, digest and
  expiry protection, truncation, concurrent source commits during capture, and
  pre-migration epoch rejection.
- Live three-league smoke: current snapshots, 9/11/9 slots, sequential API reads
  61–86 ms. This demonstrates availability, not a load-test speedup claim.
- Original app and preview returned 200. Model identity remains
  `28d3d5798840f5347df56c0c81a0be26b48b15b0232bdb5d8c5c9e70a99f926f`.

Compatibility/rollback: legacy readers still use the global revision and remain
safe with migration 0027 in place. To disable the preview, stop its services and
leave the additive tables intact. A schema downgrade to 0026 was tested, but
requires stopping/reverting the scoped preview reader first; it queries those
tables. Do not downgrade beneath an active scoped reader. Scope bindings and
counters are rebuildable metadata, not historical prediction/result evidence.

Remaining: stable prediction-artifact identity separate from grading/reporting,
then richer fantasy actions/profiles. The preview's league isolation is complete;
legacy-screen cutover, per-season shared-data granularity, and sustained
concurrency acceptance are not yet complete.

## Fourth slice: stable prospective identities — October 4 (deployed)

Replaced the fantasy prospective byte hash with a content-addressed manifest
separating prediction, capture-policy, and evaluator versions. The cohort key is
prediction + capture, not evaluator/reporting code. Selected prediction functions
include their local helper bodies, module constants/imports, scoring constants,
identity mapping, and numerical runtime versions. New untracked internal
prediction imports fail closed until the manifest inventory is updated.

Comments/docstrings/formatting do not change identity. Grading-only function
edits change the evaluator/manifest identity without fragmenting prediction
cohorts. Prediction or capture-policy changes create new cohorts. This remains
conservative: mixed prediction/presentation code in the decision builder,
module-level constants/imports, and numerical dependencies may legitimately
change a prediction identity. This is not a trained-weight registry or model
promotion. Forecast input/scoring evidence remains necessary independently.

Capture is now a separate function from evaluation. New forecast records carry
manifest references; manifests are atomically archived create-only under
`fantasy-prospective/manifests/`. Conflicting existing manifests abort capture.
Evaluation reports identify the evaluator that produced their grades. Provider
forecasts keep their existing provider recipe/observation deduplication rules.
Existing forecasts are not overwritten to add missing references.

First adoption deliberately starts a new cohort. Old byte-hash observations and
their grades remain separate, with no aliasing, retrospective qualification, or
promotion. Prediction calculations and qualification thresholds were not changed.

Verification:

- Final non-live suite: **773 passed, 1 skipped, 20 live tests deselected**.
- Identity tests cover grading-only edits, prediction/capture edits, comments,
  constants/transitive local helpers, missing functions/imports, runtime and
  mapping changes, immutable registry conflicts, legacy version retention,
  deduplicated captures, and two prospective task runs on separate event loops.
- Coordinated graceful rollout of API/worker/evaluation/beat and preview API
  after workers reported idle; dashboard/database containers were not recreated.
- Backend release audit: all four services matched **254 source/config files**
  and pinned dependencies.
- Live prospective evaluation task `c80e5f38-3a51-4e20-af29-fefe849de737`
  completed in 7.33 seconds, captured **80** new player-game forecasts, archived
  the manifest, and produced a matching report at `2026-10-04T21:43:56Z`.
  `serving_enabled` remained false. These are captures, not graded independent
  trials or evidence of improved accuracy.
- All three league checkpoints recovered through the normal background refresh
  (9/11/9 slots). Final overview reads were 55–73 ms; original fantasy matchup
  and preview returned HTTP 200 (321 ms and 73 ms complete-response samples).
  These are individual smoke observations, not concurrency percentiles.

Deployed identity:

- Prediction: `84218a86d190c5cd3b7a75b26468a77dbbc9673996a88f3eb5cf343dbc7a8861`
- Capture: `a50750dbe11d7612b1ebba3bbe09aaed2ab8b4d019b0d3a89f7299f2da56bd06`
- Evaluator: `9221376cce5ce34238394380cb33cec971299bf4d33c53ffe1222c4472b1f1f9`
- Cohort: `d6ec2b276e397e960fff508c7a7a8c96669b5aa0c1596faaf2d013d65639dee5`
- Manifest: `9e7d31c8941044b16744e2d85190d1dc68def7ff5605170bb0d66d517ef68cf8`

Celery has no result backend; the verification attempt to await AsyncResult
reported that limitation after successfully enqueueing the task. Completion was
verified through the persisted report/manifest and the matching worker success
log, not by re-enqueueing it. Continue using durable outputs for job verification.

Rollback images were retained locally before cutover (do not prune them until
the release is accepted): API `f969e74c3ac22c4de2e29d251eea61b161f5fa044ddec42ac04bbcc0d14eb5d9`,
worker `3f32ab9a99490416ebf35bbce049b1e5dca047c28fb11cabfaa927b04c3650ea`,
evaluation `b74d184003f487ef71604b4f15c559319d069d0566f4c54f392aaffafa865dba`,
beat `eadaab470ab474e11f921614353ee1be56a4f6ea85e217072c200d9065009c84`.
A rollback must restore matching backend/preview code together; immutable new
cohort records remain archived and must not be relabeled or removed.

Next: bring richer matchup/player/action workflows into the preview, expose
these identities in the evidence UI, and measure sustained concurrency. Stable
identity infrastructure is deployed; broader opportunity/availability modeling
and the full product overhaul are still open.

## October 4: matchup and lineup decision presentation

Deployed only the parallel workspace API/dashboard on port 13001. The main
app, workers, prediction math, and capture pipeline were not restarted or changed.
The main API intentionally retains the previous additive workspace response until
its next coordinated deployment; the preview uses its own updated API.

- Added current matchup rosters, observed platform scores, separately gated
  pregame totals, starter estimates and source labels, and slot coverage.
- Added candidate-vs-current starter set comparisons. FLEX rearrangements do
  not invent swaps. Missing identities, duplicate starters, incomplete slots,
  stale decision status, and changes involving locked players withhold changes.
- Unknown kickoff/identity locks remain conservative. No live remaining-points
  estimate, win probability, transaction, or model promotion is introduced.
- New decision panels use the existing snapshot expiry wrapper and checkpoint
  read; there are no extra model builds or provider calls on page loads.

Validation: 784 tests passed, one skipped, 20 live tests deselected; 16 frontend
tests passed; lint, TypeScript, generated contract, and container production build
passed. Browser verification included the expanded current-starter list. All three
leagues returned current checkpoints with 9/11/9 candidate slots; sequential
overview samples were 57–73 ms (not load percentiles).

Running preview prediction, capture, and cohort hashes match the preceding
release exactly. The production build sealed successfully during image creation.
A separate post-deployment seal verification command was not executed because
the automatic approval service exhausted its usage limit; that check remains open.

Next: checkpoint-backed waiver/player detail workflows, model-identity evidence
display, and sustained concurrency measurements. The broader overhaul is not
complete, and no new qualified probabilities are claimed.

## October 5: checkpoint-backed roster evidence and waiver research

The pending October 4 dashboard integrity check passed before this release.
Added additive overview contracts and Fantasy-only panels for roster player
evidence and saved waiver alternatives. Today remains the compact matchup view.

- Player details preserve unknown versus zero estimates, conservative locks,
  projection observation time, platform injury designation, canonical identity,
  history status/count/through-date, and missing scoring categories. Missing
  roster players remain visible as unresolved instead of silently disappearing.
- Waiver alternatives require a uniquely bound owned roster, known unlocked
  add/drop players, a nonstarter owned drop, an unowned replacement-pool add,
  positive finite gain, and the stored unstarted-slot comparison scope/status.
  Rejected candidates are counted; empty results are not called zero value.
- Gains remain stored optimizer outputs, not new calculations or ROS values.
  Alternatives are not a combined transaction plan. Platform claim timing,
  budget, availability and roster rules still require confirmation. No claims
  are submitted; news integration and calibrated probabilities remain absent.
- Both panels use checkpoint reads and the existing expiry wrapper. No extra
  provider requests, forecast builds, model changes, or background jobs were added.

Validation: 794 backend tests passed, one skipped, 20 live tests deselected;
16 frontend tests, lint, TypeScript, generated-contract check and production
build passed. Deployed only workspace API/dashboard. All three league snapshots
were available (9/11/9 candidate slots); sequential reads measured 55–74 ms,
not concurrency percentiles. Browser checks confirmed the no-move state and an
expanded player evidence card. New dashboard post-deployment integrity check
matched all 166 artifacts with no missing, unexpected, or changed artifacts.

Remaining: richer player search/comparison, ROS/trade replacement workflows,
identity manifest evidence UI, sustained concurrency measurements, and the
broader modeling and product overhaul. The main app deliberately remains on its
previous release; no cutover, model promotion, commit, or push was performed.

## October 5: roster comparison and ROS evidence

Added a two-player comparison inside the Fantasy preview using the same saved
overview, with no additional requests or model generation. Selectors contain the
owned roster only, prevent selecting the same player twice, and reset across
league/snapshot changes. The existing expiry boundary hides the comparison.

Additive player contracts expose stored full ROS candidate points separately
from known-schedule modeled subtotals, remaining game counts, unknown kickoffs,
and the horizon. Full ROS display requires exact identity, complete schedule
status, candidate scoring history, and no missing scoring keys; missing values
remain unknown, while genuine zero values remain zero. Unknown kickoff counts
stay visible rather than deleting those scheduled games.

This is evidence comparison, not trade pricing: constant-role/participation
assumptions remain, with no dynasty, keeper, injury recovery, or new model
qualification. No prediction/capture logic was modified. League-wide discovery
and package trade analysis remain separate unfinished work.

Validation: 800 backend tests passed, one skipped, 20 live tests deselected;
16 frontend tests, lint, TypeScript, generated contract and production build
passed. Preview API/dashboard deployed; all three league checkpoints available,
sequential overview samples 57–76 ms (not load percentiles). Browser selection of
two quarterbacks confirmed side-by-side stored ROS values while weekly estimates
remained withheld after kickoff. Main app/workers were not redeployed.

## October 5: league checkpoint discovery

Expanded comparison to the saved league catalog, including other rosters and
unrostered checkpoint players. Added client-side name/position/team search and
ownership filters; selected players persist while filters change. No new API
calls or model generation occur during search. The catalog is explicitly not
the complete NFL universe or a live claimability check.

Ownership labels require corroborating player roster IDs and roster membership.
Missing, conflicting, or multiply owned records stay unknown; unresolved roster
members remain in the catalog. Snapshot-unrostered is not labeled claimable.

Validation: 802 backend tests passed, one skipped, 20 live tests deselected;
17 frontend tests, lint, TypeScript, generated contract and container production
build passed. Preview-only deployment; all league snapshots available and
sequential API samples 57–76 ms. Browser verified 269 checkpoint players in the
selected league, search plus ownership filtering to a single other-roster
player, preservation of the first selection, and the resulting cross-roster
comparison. No model math, qualification, main-app deployment or transactions
changed. Trade-package impact and sustained concurrency testing remain open.

## October 5: checkpoint-only trade-package research

Added an authenticated, non-mutating POST calculation route on the preview API
and server-side dashboard proxy. It reads only the current checkpoint, requires
the submitted snapshot generation timestamp to match, and never falls back to
model generation or provider access. Numerical evaluation reuses the existing
fantasy_values.compare implementation in a threadpool; model logic is unchanged.

The UI supports up to six players per side for equal-size packages. Ownership
must be corroborated and the packages must belong to two distinct rosters.
Duplicate/unknown players and changed/missing checkpoints are rejected. The
preview's stricter full-ROS identity, schedule, and scoring gates apply to all
supporting players, not just the trade pieces. Withheld results suppress all
numeric lineup gains; displayed results inherit checkpoint expiry. No trade is
submitted and there is no inferred acceptance or fairness verdict.

Uneven packages are explicitly withheld in this preview until add/drop planning
is implemented. The existing values tool retains its explicit adjustment plans.
Conditional offensive lineup points/game are not ROS gains; byes, injury
recovery, keeper pricing, market fairness, transaction timing, and actual
availability are not resolved by this slice.

Validation: 810 backend tests passed, one skipped, 20 live tests deselected;
17 frontend tests, lint, TypeScript, generated types and production build passed.
Deployed only preview API/dashboard. Live browser evaluation returned withheld
for traded-player availability and incomplete roster/availability, with no
numeric gains. All three league checkpoints remained available; sequential read
samples 59–83 ms, not concurrency percentiles. Main app, workers and prediction
math remain unchanged. Next: explicit two-sided uneven-trade add/drop plans,
better blocker drill-down and sustained calculation concurrency checks.

## October 5: explicit uneven-trade adjustments

Preview requests now carry bounded add/drop plans for both sides, passed to the
retained trade evaluator. Unknown, duplicate, overlapping, excessive, owned-add,
uncorroborated-drop and locked/unknown-game adjustment players are withheld.
The evaluator enforces drop ownership and unchanged roster size on both sides;
availability and full-roster evidence gates remain intact. Returned sides expose
before/after roster sizes while numeric gains remain hidden for withheld results.

The UI lists only known-unlocked, ownership-eligible adjustment candidates, uses
stable roster IDs rather than team names, prevents duplicate selections, and
displays net roster-size changes. Changing either package clears both adjustment
plans. Claimability, FAAB, waiver timing and actual transaction legality remain
unverified; no roster changes or claims are submitted.

Validation: 818 backend tests passed, one skipped, 20 live tests deselected;
17 frontend tests, lint, TypeScript, generated contract and production build
passed. Tests cover a fully balanced two-for-one plan plus invalid ownership,
duplicates, unknowns, locks, injuries and unbalanced plans. Preview deployed;
all three checkpoint reads remained available (60–81 ms sequential samples,
not load percentiles). Browser confirmed +1/-1 roster deltas and an explicit
addition balancing side B to zero. A checkpoint refresh during that manual
evaluation correctly withheld the request as changed; the automated tests,
not that live attempt, verified balanced evaluation. No main-app/model changes.

Remaining priorities: actionable blocker explanations with supporting player
evidence, smoother explicit refresh/review for changed snapshots, bounded
calculation concurrency and sustained performance measurement.

## October 5: trade diagnostics and explicit refresh

Trade sides now expose supporting players with missing valuation evidence or
availability flags. The UI explains common blocker codes in plain language and
provides per-team expandable player-review details. Withheld numerical gains
remain hidden; supporting players can include pre/post-trade bench members.

Added an explicit evidence refresh button. A normal in-place refresh preserves
trade selections/plans, clears prior results and requires another evaluation.
Requests finishing against an older generation are ignored. League changes
still reset state; an expired/missing checkpoint unmounts the panel and may
clear drafts, explicitly disclosed in the UI. This is not persistent draft
storage and never bypasses server-side ownership, lock or snapshot checks.

Validation: 819 backend tests passed, one skipped, 20 live tests deselected;
18 frontend tests, lint, TypeScript, generated contract and production build
passed. Preview-only deployment. Browser verified player-specific availability
details, retained both selections after refresh, and confirmed removal of the
old result. Three league snapshots remained available, with sequential reads
59–81 ms (not load percentiles). No prediction math, main-app deployment, or
transactions changed. Remaining: bounded calculation concurrency, sustained
performance tests, richer evidence drill-down and broader overhaul work.

## October 5: trade admission control and bounded mixed-load measurement

Added one non-queuing trade slot per API process. Busy requests receive HTTP 429,
Retry-After: 2, and no-store before accessing the DB. The dashboard proxy preserves
Retry-After. A caller cancellation does not release the slot until the shielded
calculation actually finishes; read/calculation failures release capacity. The
guard uses a threading semaphore rather than an event-loop-bound primitive.
This is not a distributed limit; multiple API processes would each own one slot.

Added scripts/workspace_load_check.py, restricted to loopback with at most 30
rounds and six concurrent requests. It issues only checkpoint reads and
non-mutating trade calculations, stops on transport/server errors, never retries
429s, and reports latency by HTTP status to avoid mixing rejections into accepted
calculation latency. No provider calls, model builds or ingestion are triggered.

Deployed preview API/dashboard only. Regression: 822 passed, one skipped, 20 live
tests deselected; 18 frontend tests, lint, TypeScript and production build passed.
Deployed dashboard integrity matched all 170 artifacts. Cancellation, overload,
failure recovery and two distinct event loops are explicitly tested.

Live mixed-load result (40.68 seconds, up to six concurrent requests):

| Request class | Count | p50 ms | p95 ms | Maximum ms |
| --- | ---: | ---: | ---: | ---: |
| Overview HTTP 200 | 120 | 135.87 | 254.71 | 267.40 |
| Trade HTTP 200 | 30 | 120.28 | 259.56 | 521.34 |
| Trade HTTP 429 | 60 | 2.60 | 3.58 | 4.09 |

All overview responses had available snapshots. All accepted trade requests
returned evidence-withheld results; these measurements do not establish latency
for every possible fully qualified package. No transport errors or HTTP 5xx.
This is a short preview loopback test, not a browser-navigation measurement,
long-duration soak, cross-process capacity claim or production SLO. Main app and
model logic remain unchanged. Remaining: browser navigation profiling and
longer observation under ordinary scheduled ingestion, plus broader overhaul.

## October 5 evening: navigation profiling and deferred selectors

Observed scheduled sync/evaluation activity in bounded worker/beat logs. One
resource sample showed worker 67% CPU and 1.20/1.5 GiB RAM, Postgres 127% CPU,
while preview services were nearly idle. This establishes concurrent background
work, not causal attribution or a saturation trend; no schedules were changed.

The Fantasy initial page contained 2,248 DOM elements and 1,209 select options.
Added explicit comparison/trade open controls so those selectors are built only
when used. Initial observed DOM became 989 elements and zero options. HTML
samples fell from 462,248 to 356,024 bytes; complete HTTP response samples were
246 ms before and 263 ms after, so no server-response speedup is claimed. Inputs
continued refreshing during measurement; this was not a controlled benchmark.
The full checkpoint still travels with the page; this change defers rendering,
not catalog delivery or JavaScript module download. Closing a research tool
clears its local draft, explicitly disclosed.

Reproduced query-only client navigation from Markets back to Fantasy remaining
pending with successful API reads and no browser errors. Added immediate pending
feedback, disabled logo/current-app automatic prefetch, and changed workspace tab
links to native document navigation. This fixes the observed path without claiming
to identify the underlying Next.js streaming/router defect. Trade drafts do not
persist across workspace navigation. League-selection links remain client links
and need separate regression profiling.

Verified Markets → Fantasy → Today → Fantasy: automation-observed click-to-visible
heading samples 208/498/564/494 ms. These include automation overhead and are not
browser-native performance marks or percentiles. Both research tools opened
successfully afterward. 19 frontend tests, lint, TypeScript and production build
passed, including an SSR test proving closed tools do not construct selectors.
Only preview dashboard was recreated in the final deployment; API/model logic
unchanged. Backend suite was not rerun for these frontend-only changes (last
verified 822 passed). Remaining: league-switch profiling, long-duration resource
observation, payload reduction, and the broader overhaul.

## October 5 evening: league navigation and research-prop reduction

Reproduced the remaining query-only transition failure while switching from
Sleeper to ESPN: the prior league content remained visible. Changed league
selectors to normal document links, matching workspace tabs. Verified all three
league destinations and return: 517/589/508 ms automation-observed samples,
including successful ESPN context. Drafts intentionally do not cross leagues.

Research client components now receive only league_id, generated_at and the
comparison catalog, rather than the entire overview (matchups, waivers, roster
details, notes, etc.). A regression test checks the exact allowed fields. Latest
Fantasy HTML sample was 326,532 bytes versus the prior 356,024-byte sample;
97 ms complete-response sample. These are live changing-input observations, not
a controlled throughput claim. The player catalog still travels on initial load.
Browser confirmed trade tools still receive the required context and open.

20 frontend tests, lint, TypeScript and production build passed. Only the preview
dashboard was rebuilt/recreated; no model/backend changes or backend-suite rerun.
Two focused resource samples showed worker CPU 0.07–0.10%, memory 1.211/1.5 GiB,
Postgres CPU 0% and approximately 484 MiB, preview API CPU 0.10–0.23%. Scheduler
logs showed normal scoreboard/props/schedule/refresh dispatches. These short
samples do not prove a leak or sustained contention, and do not justify changing
ingestion schedules. Longer-duration resource trending remains uncompleted.

## October 6: preview performance evidence

Queried all 288 existing operations observations, October 5 11:48 UTC through
October 6 11:44 UTC: one main-API process, zero unreachable observations and
zero observations with alerts. Peak RSS stayed at 455,139,328 bytes. This is a
high-water mark, not proof of steady current memory; five-minute observations
also cannot exclude incidents between samples. The history does not cover the
preview API, worker resource use, or database contention.

Added authenticated, no-store `/operations/performance` to the isolated preview,
with bounded route-template metrics (no league/query values). Shared telemetry
now distinguishes Linux current resident memory from process peak memory and
reports oldest/newest sample ages, so an old rolling p95 cannot masquerade as a
recent measurement. Unsupported memory reads return unknown, never zero.
The smoke script includes these diagnostics. No scheduler/provider/model changes.

62 focused tests passed twice. Rebuilt/recreated only workspace-api; production
API and workers still use their prior image, so these additive telemetry fields
are not yet deployed there. Live smoke verified all three league snapshots,
9/11/9 starters, nine overview responses taking 57–80 ms sequentially and zero
5xx. Preview current RSS was 98,549,760 bytes and peak 100,917,248 bytes. These
are backend smoke samples, not browser timings or sustained load evidence.

Remaining: durable preview/worker/database trend capture, correlation with
browser navigation, and further initial catalog payload reduction. The new
preview metrics reset on restart; they do not themselves close those gaps.

## October 6: backend foundation acceptance

Completed a foundation-only pass before further fantasy/UI implementation.
Standalone shared authentication avoids importing the production app into the
preview. Added authenticated DB readiness, container healthcheck, redacted
retryable DB failures, connection bounds, and malformed-checkpoint rejection.
Actual PostgreSQL writes are rejected and slow queries cancelled; both checks
recover after rollback and pass through two fresh preview lifespans.

A separate 192 MiB diagnostics observer now retains 288 cross-service samples
in `workspace-runtime-history`, polling every five minutes without providers,
model evaluation or Celery dispatch. Reads are available from the authenticated
`/api/v2/operations/runtime`. It probes main/preview APIs, preview readiness,
Redis waiting queues and aggregated DB activity. Fresh resources per observation
were tested across separate asyncio.run event loops. Its checkpoint writes do
not change fantasy input revisions. Missing worker CPU/RSS and running-job
evidence remain explicit limitations; an empty queue is not worker health.

Full final suite: **838 passed, 1 skipped, 20 live-provider tests deselected**.
Focused foundation suite repeated: 82 passed. Mixed-load check: 120 overview
HTTP 200 at p95 254.94 ms; 30 admitted trades HTTP 200 (all withheld by retained
model gates), 60 fast HTTP 429; no transport errors or 5xx. Source/package audit
matched all 259 files for preview API and observer. Only these two services were
deployed; main API, workers, dashboard and model logic were not changed live.

The replacement-backend baseline is accepted for the next fantasy workstream.
This is not final production cutover, browser/mobile acceptance, model promotion
or proof of sustained performance. Detailed controls, operating commands,
rollback and remaining boundaries: `2026-10-06-backend-foundation-acceptance.md`.

## October 6: fantasy-tools phase — daily review and focused workspaces

Replaced the single long fantasy page with URL-owned, allowlisted tool screens:
Overview, My Team, Waivers, Players and Trade Analyzer. League switching keeps
the current tool; navigation uses the previously verified native links rather
than reintroducing the stuck query-only client transition. Navigation clears
local trade/comparison drafts. Only the selected tool receives its client data;
overview and Today do not construct player/trade selectors.

Added a deterministic daily review: supplied player designations and missing
estimates first, then candidate lineup and waiver research. This is workflow
ordering, not a new ranking/prediction model. Zero points are not missing; no
roster is not an empty team; missing designations are not proof of availability.
Lineup cards link to My Team's complete candidate lineup. Waiver counts refer
to separate saved alternatives, not a combined transaction. Snapshot expiration
continues hiding all candidate content. Legacy links remain under a disclosure.

Compacted headings and phone navigation. Browser verification covered Overview,
My Team, nine saved waiver alternatives, player search (Bo Nix: one match in the
269-player checkpoint catalog), and Trade Analyzer. A phone-width check showed
no document-level horizontal overflow and zero selects on Overview. This is not
full mobile/accessibility acceptance or pixel parity with the reference apps.

25 frontend tests pass, including selected-tool-only SSR, URL league isolation,
missing-checkpoint withholding, and zero-versus-unknown daily-review cases.
TypeScript, lint and production build pass. Only preview dashboard is rebuilt;
backend, observer, models, production dashboard and provider schedules unchanged.
The backend suite is not rerun for this frontend-only slice (last: 838 passed).

Remaining fantasy phase: richer player-detail/start-sit flows, easier searchable
trade-package selection and explanations, waiver decision ergonomics, and the
full reference-driven visual design. This slice reorganizes existing evidence
and does not claim improved prediction accuracy or a completed fantasy overhaul.

### Follow-on fantasy slice: player research

Players now has searchable 20-row result pages, single-player evidence and an
optional second-player comparison instead of two catalog-sized dropdowns. One
ownership select remains. Selecting a player focuses the evidence heading;
filters reset pagination but retain selected players. Navigation/new checkpoint
remounts clear selection. The catalog still comes from the same full checkpoint;
pagination reduces rendered controls, not backend catalog loading.

Added visible canonical identity and projection/history timestamps alongside
weekly and conditional ROS evidence. No start/sit winner, trade value or injury
recovery is inferred. Daily-review counts exclude routine ACTIVE/HEALTHY labels
but preserve those labels in player detail; missing labels remain unconfirmed.

Browser verified 20 initial rows and one select, Bo Nix detail, comparison with
C.J. Stroud, removing the comparison, page 2, and search resetting to one result.
The test league was ESPN; values/ownership are league-specific and not copied
from the earlier Sleeper screen. 28 frontend tests, lint and TypeScript pass.
Only the preview dashboard is deployed; model/backend logic unchanged.

Final browser check: phone-width player detail had equal document/client widths
(375 px), focus moved to the selected player's heading, and no browser errors
were reported. ESPN briefly withheld player tools for an unavailable checkpoint;
the final single-player check used a current Sleeper checkpoint. No freshness
gate was bypassed. Final production build passed; source and sealed artifact
verification matched. A visible manual refresh affordance for the initially
unavailable-checkpoint state remains a useful follow-up (expired-state refresh
already exists). Full visual parity and accessibility acceptance remain open.

### Follow-on fantasy slice: team-aware trade selection and waiver review

Replaced all-player trade dropdowns with searchable team-filtered pickers, capped
at 12 visible matches per side. The first selected player binds one corroborated
roster; the opposite side excludes that roster. Missing, duplicate, mixed or
uncorroborated package ownership fails closed. Evaluation requires two distinct
known owners; backend evidence gates remain authoritative. Package changes clear
adjustment plans and results. Closed plans defer their four dropdowns: browser
verified two selectors closed and six open. Search adds no provider calls.

Waivers group by added-player position and sort by estimated unstarted-slot gain
within each group, not ROS value. Each original addition retains its corresponding
drop; alternatives are not combined. Initial missing-checkpoint screens now have
a native retry link preserving league/tool, without dispatching any refresh job.

32 frontend tests, TypeScript, lint and production build passed. Browser verified
Bo Nix versus A.J. Brown package creation, distinct team constraints and an actual
withheld result with roster/availability reasons. No trade was submitted. Grouped
waiver alternatives rendered correctly. Phone-width trade and waiver views had
equal document/client widths (375 px); no browser errors were reported.

Only the preview dashboard was deployed. The final source/sealed-artifact audit
was NOT executed: the approval service failed due to a usage limit. This is a
verification gap, not detected release drift. Retry the normal approved audit
when that service is available; do not bypass its approval requirement. Backend,
model and production services were not changed in this slice.

Remaining: final release-manifest verification, deeper start/sit and lineup-change
explanations, richer player-detail navigation and the broader visual overhaul.

### Follow-on fantasy slice: lineup review and linked player evidence

My Team now compares saved current starters and the candidate lineup, distinguishes
slot reassignments from candidate additions, and opens preselected player evidence.
Row correspondence is withheld when slot layouts differ; current starters remain
separately inspectable. Zero points remain zero and missing points remain unknown.
FLEX movements are explicitly not independent one-for-one swap recommendations.

Roster detail and paired waiver alternatives now link to player research. Linked
IDs are validated against the current league checkpoint catalog without fallback
to unrelated players. Player research reports current/candidate membership only
for the corroborated own roster, and does not infer assignments for other players.

Validation: 34 frontend tests, TypeScript, lint and production build passed. Only
workspace-dashboard was redeployed. The normal approved release audit succeeded:
80 source files, no missing/unexpected/changed files, 171 sealed artifacts matched.
This closes the preceding slice's release-verification gap.

Browser verified C.J. Stroud versus Bo Nix from My Team, including correct current
starter/candidate membership; Cincinnati Bengals versus Jaxson Dart from Waivers,
including distinct ownership and withheld unsupported ROS evidence. Mobile lineup
and comparison checks had equal document/client widths (375 px); viewport override
was reset. No browser console errors were reported during these checks.

Fantasy workflow navigation, paired evidence review, and deployment verification
are implemented. This is not full fantasy-model acceptance: live defense research
still exposes unresolved canonical/ROS evidence, missing availability remains
unconfirmed, and prospective qualification is not established by these UI tests.
No gates were weakened, forecasts promoted, or external transactions submitted.
Broader UI redesign remains deferred under the user's fantasy-first instruction.

### Follow-on fantasy slice: specialist uncertainty evidence and availability

The preview API and player/roster research now expose saved distribution evidence
separately from ROS component history: usable finite sample counts, source,
reconciliation checks/mismatches and explicit assumed-prior labeling. Synthetic
positional assumptions never count as observed history. Missing evidence remains
unknown. This presentation module is outside the fantasy recipe glob, so it does
not invalidate model checkpoints or change their version.

Availability labels distinguish missing designations, reported restrictions,
no-restriction reports (not game clearance), and team defenses (not individual
injury status). No eligibility or promotion gates changed. No provider calls or
new model calculations occur on page reads.

83 focused backend tests passed including real isolated test-database checkpoint
and read-only foundation checks. The initial sandboxed database tests could not
connect; the normal approved rerun against fantasy_edge_test passed. 34 frontend
tests, TypeScript, lint, generated API types and production builds passed.
Deployed only workspace-api and workspace-dashboard. API 260 source files match;
dashboard 80 source files and 171 sealed artifacts match, with no source drift.
The observer and production workers were intentionally not redeployed.

Browser verification: Cincinnati defense displayed 20 usable reconciled component
samples, 50 scoring checks and zero mismatches. Previously only its unsupported
ROS history was visible. Full ROS remained withheld and canonical player identity
remained unresolved; this does not resolve defense-as-team identity or qualify a
ROS forecast. Browser reported no console errors. Remaining acceptance work:
defense team identity, independently validated specialist ROS, game-specific
availability and prospective qualification. This slice does not close those.

### Defense team binding in the preview

Added a separate canonical team binding for Sleeper DEF/DST records. Provider
defense ID and metadata abbreviation must agree (bounded existing aliases), and
exactly one canonical NFL team must match. Wrong sport, conflicting IDs, duplicate
aliases, missing teams and unsupported ESPN numeric IDs remain unresolved. No
name matching or fabricated individual-player identity is used.

Canonical teams are read in the same SQL statement as checkpoint/revision data.
The persisted forecast and its original identity field are not mutated, and team
binding cannot satisfy the existing individual-player ROS qualification gate.
This closes Sleeper team-identity presentation, not serving-model identity or
specialist model validation. ESPN defense binding remains open until corroborated
provider team evidence is carried through rather than inferred from numeric IDs.

89 focused backend tests passed, including real test-DB checkpoint binding and
invalidation. 34 frontend tests, TypeScript, lint, generated types and production
build passed. Deployed preview API/dashboard only; 260 API source files and 171
dashboard sealed artifacts matched. Browser confirmed Cincinnati as exact team
with canonical UUID, 20 usable samples and ROS still withheld; no console errors.
Production model workers and observer were not redeployed.

### ESPN defense evidence retention and binding

Implemented explicit ESPN defense player-ID/proTeamId corroboration, with canonical
NFL team and metadata-abbreviation agreement. Missing, conflicting, stale (>6h),
or post-checkpoint evidence remains unresolved. Numeric fantasy IDs are not
converted to team IDs. Identity does not promote ROS or alter saved predictions.

Live verification corrected an implementation assumption: league.raw deliberately
retains only scoring settings, not the provider roster payload. The initial live
check therefore resolved no ESPN defenses. Ingestion now retains only rostered
defense identity pairs in raw.defense_identities; account and full roster payloads
remain discarded. The corrected reader consumes this minimal field atomically
with checkpoint data. 98 focused backend tests passed, including real test-DB
fresh/stale/future evidence and privacy-preserving extraction. Generated types
remain unchanged. Preview API deployed and source checked.

NOT closed live: the scheduled production ingester was not redeployed, so existing
league records still lack the new evidence field. A scoped ingester release and
normal ESPN sync are required before live resolution can be accepted. Free-agent
defenses are also not covered by the retained roster-only pairs. Dashboard,
production model workers, and validation gates were not changed in this slice.

### ESPN defense ingestion closure

Extended the common roster/free-agent player recorder to retain provider team-ID
observations, including conflicts. The sync persists minimal defense identity
pairs after free-agent collection, without retaining account payloads. Regression
coverage checks repeated sync wiring and conflicting free-agent observations.
103 focused ingestion/workspace tests passed; a separate 45-test fantasy
compatibility group passed after updating the exact retained-field assertion.
These groups overlap and should not be summed as distinct test coverage.

Compared production worker source before deployment: no forecast/model-math drift;
differences were preview/API infrastructure and ESPN ingestion. Deployed worker
only, verified zero source drift, and dispatched one normal ESPN sync. Celery has
no result backend; completion was verified from stored data and the live preview,
not assumed from task dispatch. Sync at 2026-10-07T12:18:32Z retained 50 observations
covering all 32 defenses. The subsequent current preview showed all 22 included
defenses as exact_team, covering rostered and unrostered players (including the
user's Packers defense). All ROS values remained null. One API smoke sample was
92.51 ms; this is not a latency percentile or performance acceptance test.

This closes the prior scheduled-ingester deployment and free-agent identity gaps.
The existing 15-minute ESPN schedule now uses the updated worker. Remaining fantasy
acceptance work is specialist ROS validation, game-specific availability, and
prospective qualification—not defense identity presentation. No model promotion,
external fantasy transaction, database migration or threshold relaxation occurred.

### Fantasy sweep: event-linked availability and acceptance

See `2026-10-07-fantasy-sweep-acceptance.md` for the implemented availability
integration, full regression results, coordinated deployment/source verification,
live league smoke checks and explicit completion ledger. Fantasy research workflows
are deployed; full model qualification is not claimed. Browser acceptance was
blocked by an approval-service usage limit, and missing-result/specialist ROS work
remains open separately from genuinely future-dependent prospective evidence.
