# Overhaul status and UI direction — October 6, 2026

## Completion assessment

Approximately the first third of the replacement effort is implemented. This is
a planning judgment, not a measured percentage of a fixed backlog. Existing
legacy functionality is not counted as rewritten merely because the new shell
links to it. Passing tests and fast API reads are not model qualification or
whole-product acceptance.

| Workstream | Verified implementation | Still required |
| --- | --- | --- |
| Foundation | Accepted replacement-backend baseline: isolated deployment, authenticated checkpoint reads, scoped invalidation, stable evidence identities, bounded DB/trade work, durable diagnostics, fault/load/release checks | Long-duration observation and final production cutover remain separate acceptance steps; see 2026-10-06-backend-foundation-acceptance.md |
| Fantasy workflows | Matchup contributions, roster evidence, waiver candidates, player comparison, checkpoint-based trade packages with explicit add/drop plans | Cohesive daily brief, dedicated player/detail and task screens, refined action ranking, end-to-end workflow parity |
| Visual overhaul | Responsive functional dark preview, league navigation, deferred research selectors | Reference-driven design system and complete desktop/mobile screen rebuild; current UI is not visual parity |
| Prediction models | Retained models and evidence gates exposed; stable prospective identity infrastructure | Separately evaluated opportunity/availability and correlated outcome models; remaining K/DST/rookie qualification; evidence of improvement |
| Markets and research | Workspace entry points to existing tools | Native rebuilt comparisons, ledger workflows, research/actionable separation throughout, validated parlay correlation handling |
| Cutover | Legacy retained, preview separately deployable | Screen parity, regression/accessibility/performance acceptance, coordinated deployment, duplicate route retirement |

## User-directed visual target

WalterPicks is the primary visual reference; FantasyPros/My Playbook is the
primary league-management and information-organization reference. The target is
a polished personal sports app, not a developer console or a marketing landing
page. Keep Fantasy Edge identity. Match observed screen patterns closely rather
than inventing claims of pixel parity with unobserved signed-in screens.

Public references consulted:

- https://www.walterpicks.com/ — league-specific fantasy and betting tools,
  trade analyzer/finder, start/sit, ROS and waiver workflows.
- https://www.fantasypros.com/myplaybook/screen-shots/ — league switching,
  roster/available/taken distinctions, player comparison and player notes.
  These published screenshots may be older than the current signed-in UI.
- https://support.fantasypros.com/hc/en-us/articles/360018746693-What-is-the-My-Playbook-Dashboard-NFL
  — personalized dashboard connecting team insights to deeper tools.

Requested current user screenshots for exact layout/theme/detail matching.
Public image retrieval did not succeed this turn; no claim of screenshot-based
visual verification is made. Those references describe product patterns, not
proof of either provider's predictive accuracy.

## Next implementation order

1. Rebuild the shell and Fantasy home visually: compact header, persistent league
   context, desktop navigation rail, mobile navigation, matchup scorecard and
   prioritized decisions. Replace large preview slogans and repeated technical
   paragraphs with concise contextual labels and accessible evidence details.
2. Dedicated My Team, player detail, start/sit, waivers, and trade surfaces using
   one design system: compact aligned numeric rows, ownership/availability labels,
   searchable player selection, consistent cards, loading and empty states.
   Keep working native navigation until a client-navigation replacement passes
   regression tests. Do not remount hidden heavyweight controls on every page.
3. Bring Markets, ledger, parlay research and Experiments into the same shell
   instead of sending the user through a second application design.
4. Continue model/data qualification behind these surfaces, then run full
   functional, mobile, accessibility and performance acceptance before cutover.

## Personal-use constraints and acceptance

- Optimize for this user's actual leagues and daily decisions. No billing,
  subscriptions, marketing funnels, social feed, multi-tenant permissions or
  organization administration. Keep local authentication and secret protection.
- Visual polish must not imply nonexistent expert consensus, licensed news,
  live data, prediction confidence or model qualification. No invented grades,
  win probabilities or actionable trade/bet labels to fill a reference layout.
- Show essential stale/unknown/locked/research labels beside the affected value;
  put detailed lineage and limitations behind expandable evidence sections.
- Validate main workflows at phone and desktop widths, including keyboard use,
  focus visibility, error/loading states and league transitions.
- Reference comparisons must be screen-by-screen, not just a palette change.
  Exact pixel matching needs matching reference screens and viewport dimensions.
- Work in the preview first. Keep the old app accessible until parity is proven.

This turn records status and design requirements. It does not deploy a redesigned
UI or declare any new model qualified.

## October 12 update — progress check and projection-engine integration

### Progress since October 6 (from the ledger, sweep docs and working tree)

| Workstream | Changed since Oct 6 | Status |
| --- | --- | --- |
| 1. Foundation | Migrations 0019–0027 (model evidence, forecast archives, deployments, derived checkpoints, fantasy input revision/invalidation/scope revisions); workspace API/app split; auth proxy; runtime/operations history | Accepted baseline (Oct 6). **None of it is committed** — last commit is `59e8b27` (Sep 23); ~220 working-tree changes, 159 untracked files. Long-duration observation and cutover still open |
| 2. Fantasy workflows | URL-owned tool screens (Overview, My Team, Waivers, Players, Trade); daily review; player research; team-aware trade selection; lineup review; deterministic waiver ties + alternative drops; keeper rules/valuation scenarios + draft archive (180 picks, all `is_keeper` null); multiweek retention pipeline (scheduled every 30 min) | Research workflows deployed in preview. Retention blocked: projection archives only reach ~2 weeks ahead. Keeper surplus pricing, FAAB and dedicated detail/start-sit screens open |
| 3. Visual overhaul | Compact headings and phone navigation only (Oct 6) | **Deferred** since Oct 7 per the fantasy-first direction. Shell/home rebuild (step 1 of the order above) not started |
| 4. Prediction models | Specialist full-score shrinkage research; specialist prospective capture; Sleeper component-result recovery; event-linked availability | No model qualified; kicker recency candidate lost its holdout. Opportunity/availability and correlated outcome models **not started** |
| 5. Markets and research | Parlay assistant + workspace parlay routes added | Native comparisons/ledger rebuild open |
| 6. Cutover | — | Not started |

**Currently in progress:** `2026-10-10-fantasy-closeout-plan.md` (last edits
Oct 10 13:29: `retention_pipeline.py`, `fantasy_decision_models.py`,
`fantasy_prospective.py`, `workspace.py`, `celery_app.py`, `docker-compose.workspace.yml`).
Items 1–4 have code and tests in the working tree; item 5 (full regression,
coordinated deploy, multi-league localhost verification) has no recorded
result after Oct 10. No other Claude session is currently working in this repo.

### Integrated: projection & decision engine

Researched against WalterPicks, FantasyPros, Sleeper (RotoWire-licensed
projections), ESPN, Yahoo, PFF, 4for4, numberFire and RotoWire using public
methodology only — no app decompilation (models are server-side; terms of
service prohibit it). Industry recipe: Vegas game environment → team volume →
player usage share → efficiency → injury adjustment → per-stat projection →
league scoring → distributions → correlated Monte Carlo → decisions, graded
with a FantasyPros-style accuracy harness. Full research plan:
`~/.claude/plans/jazzy-finding-river.md`.

Engine phases mapped onto the workstreams:

| Engine phase | Workstream | Integration point |
| --- | --- | --- |
| E1 Data: nflverse snap/opportunity usage table; implied team totals from existing `TeamMarketLine`; Sleeper season projections | 1 Foundation | Next migration after 0027; verify nflverse shapes live first; constraint #2/#13 |
| E2 Projection engine (volume → share → efficiency, Sleeper stat keys, append-only `fantasy_player_projections`) | 4 Models | Replaces the ±1SD clamp in `roster_stat_model.py`; reuses scoring dot product in `fantasy_decision_models.py` |
| E3 Injury participation probability + volume redistribution | 4 Models | Fills `lab_availability.participation_probability`; builds on event-linked availability |
| E4 Per-stat distributions + correlated Monte Carlo | 4 Models | Upgrades `fantasy_simulation.py`; replaces fixed K/DST SDs (specialist work) |
| E5 Accuracy-weighted consensus (Sleeper + engine + de-vigged props) | 4 Models / 5 Markets | Reuses `odds_math` and existing prop ingestion |
| E6 Decisions: win-probability lineup mode, FAAB ranges, playoff-odds trades, ROS with byes | 2 Workflows | **Unblocks retention**: engine produces genuine future-week projections that Sleeper archives lack; still labeled as model output, never copied forward |
| E7 Accuracy harness + fantasy promotion criterion | 4 Models / 6 Cutover | Uses existing `fantasy_prospective` capture; adds the missing fantasy criterion to `prospective_review`. `serving_promoted` stays false until passed |
| UI for E2–E6 (floor/ceiling bars, win probability, research columns beside Sleeper) | 3 Visual | Built into the WalterPicks-style shell, labeled research until E7 passes |

### Revised next order

1. Finish closeout item 5 (regression, deploy, verify), then **commit the
   working tree** in reviewable slices — four weeks of uncommitted work is the
   largest current risk.
2. E1 data foundations (independent of the UI; starts accruing graded weeks sooner).
3. E2 + E7 harness together, so engine forecasts are captured prospectively from first deploy.
4. Visual step 1 (shell + Fantasy home), showing engine output as research columns.
5. E3–E4, then E6 decisions and visual step 2 screens.
6. E5 consensus, Markets into the shell (visual step 3), then cutover acceptance.

The engine does not change the existing boundaries: no automatic promotion, no
invented confidence or grades in the UI, missing stays missing.

## October 12 progress — revised steps 1–4 complete

1. **Closeout item 5.** Full regression 957 passed / 1 skipped (first run blocked:
   the Colima Docker disk was 100% full, 94/99G — the raw archive is 70G and
   the live worker had logged 868 `No space left` errors in 6 hours, so
   ingestion and capture were failing). Owner-approved fix: pruned 9.6G build
   cache, grew the Colima disk to 200G (brief full-stack restart; all 14
   containers returned). `raw_retention` compressed nothing: no
   result-observation file is past its 90-day minimum, and several audit
   scripts read only `*.json`, so that policy was left unchanged. The archive
   grows roughly 1G/day; retention policy remains an owner decision. Frontend:
   tsc, lint, 37 tests pass. Release audit: only the workspace observer had
   drifted (rebuilt). All three leagues serve snapshots; workspace tool pages 200.
2. **Committed** on branch `overhaul/checkpoint-2026-10-12` in seven layer
   slices (not pushed). Intermediate slices are not individually tested.
3. **E1 data foundations (deployed).** `player_snap_counts` (0028), refreshed
   daily from the nflverse release CSVs (the serving image has no nflreadpy).
   Current-season games carry no `nflverse_game_id` (0/272), so snaps match
   by exact season/week/away/home fixture, read-only. 2026: 2,872/2,881
   offensive rows, all 78 games; 2025: 10,066 rows, 272 regular-season games
   (13 postseason games unmatched). Usage shares and point-in-time,
   same-source implied totals (`game_environment.py`).
4. **E2 engine + E7 harness (deployed).** `projection_engine.py` and
   `projection_engine_prospective.py`; scheduled every 30 min on the
   evaluation queue. First run froze 36 pregame projections; 28 paired with
   Sleeper and awaiting final. Retrospective paired backtest (2026 weeks 2–5,
   831 player-weeks, `scripts/backtest_projection_engine.py`): engine MAE 5.94
   vs Sleeper 5.81; starter pool 7.27 vs 7.32, difference −0.05 (week-bootstrap
   95% CI −0.22 to +0.05). RB worse (+0.42, CI +0.13 to +1.15); the engine
   under-projects top players more than Sleeper (pool bias −2.6 vs −1.6).
   Retrospective and four weeks only: not evidence of improvement. Promotion
   criterion (current version only, ≥6 graded weeks, pool CI below zero, no
   position CI above zero) is reported, never applied.

Next: visual step 1 (shell + Fantasy home) with engine projections as
labeled research columns; tune shrinkage on 2025 walk-forward (never on the
graded 2026 weeks), then E3 injuries and E4 distributions.

### October 12 — engine retune and disk-growth findings

- **Retune** (`scripts/tune_projection_engine.py`, owner-directed 2025+2026
  walk-forward): starter-pool MAE 5.739 → 5.703 (half-life 2 games, rate
  pseudo-counts ×2). Chosen on 2025 alone, no setting improved 2026 out of
  sample, so the gain is marginal. Calibration over all players shows no star
  under-projection (20–27-point bucket: 21.3 projected vs 20.3 actual); the
  negative pool bias is the pool selecting on actual results. Real flaws:
  fringe players over-projected (4.8 vs 4.0) and QBs +1.75 (backups shrunk
  toward a starter's share). A per-team share cap was rejected (5.74 → 6.50)
  because without active-roster status every player last seen on a team
  counts; this belongs to E3. Paired vs Sleeper (2026 weeks 2–5, now
  in-sample): pool 7.19 vs 7.18; QB better, RB worse. New capture version
  `fe842bf5…` deployed before Week 7.
- **Disk growth**: the raw archive grows ~16 GB/week (result-observations
  6.1, fantasy-prospective 2.7, roster-evidence 2.2 at ~100 MB per 6-hourly
  file, grading 1.2). Only 13% of result payloads are exact duplicates, but
  gzip shrinks the bulky kinds 14–26×. Build cache regrows ~10 GB per day of
  rebuilds. At current growth the 200G disk has roughly six weeks of headroom.

### October 12 — disk growth fixed; E3 amended for the engine's real flaws

**Disk (all three owner-approved items done):**
1. Hourly `fantasy.compress_raw_archive` (evaluation queue) losslessly gzips
   day-old files in `raw_retention.COMPRESSIBLE` — append-only directories
   only, never create-only identity records — within a 2 GB/run budget. All
   readers of those directories use `src/utils/archive_io`. First batch:
   1,188 files, 2.0 GB saved of 2.1 GB read; ~68.7k backlog files drain in
   ~1.5 days. Expected steady growth ~1 GB/week instead of ~16.
2. The hourly data-health check now alerts via ntfy at 80% disk. Note: the
   existing `~/bin/check-colima-disk.sh` Uptime Kuma push monitors the same
   disk at 85% and should have reported "down" during the Oct 12 fill —
   check that monitor has a notification attached.
3. Weekly launchd prune (`~/bin/docker-weekly-prune.sh`, Tuesdays 04:30):
   build cache above 5 GB and dangling images only; never volumes or the
   `grading-preview-before-*` rollback containers. First run: cache 10 → 5.4 GB.

**Does the plan fix the engine's flaws? Partly — E3 as written is not enough.**
The walk-forward flaws are backup QBs and fringe players getting a typical
player's share (QB +1.75 pts, fringe 4.8 vs 4.0), and a per-team share cap
failed because the engine cannot tell who is active. E3 as written covers
injury designations (Q/D/O participation probability) and vacated-volume
redistribution, which handles injured starters but not healthy backups.
Amendment to E3:
- Keep Sleeper's `status`, `depth_chart_position` and `depth_chart_order`
  in the player catalog. `/players/nfl` already returns them (610 of 832
  rostered QB/RB/WR/TE have a depth order; KC: Mahomes 1, Fields 2,
  Nussmeier 3) but `src/ingest/sleeper.py` trims them out.
- Archive the catalog's depth/status daily so it is point-in-time evidence;
  no historical depth charts exist, so this can only be validated
  prospectively, never by backtest.
- Then re-enable a per-team share cap over active, depth-charted players
  only, and give depth-1 QBs the QB pass share (backups only via E3's
  vacated-volume path when the starter is out).
- The RB gap vs Sleeper is better addressed by E5 (accuracy-weighted blend
  with Sleeper/RotoWire) than by the engine alone.

## October 12 — overhaul review from the top; fantasy area finished to research parity

### Review of all six workstreams (what was improved, what is still open)

| Workstream | Finding on review | Action this pass |
| --- | --- | --- |
| 1 Foundation | Sleeper catalog ingest trimmed `active`, so the catalog's "active players only" filter was a silent no-op; depth/status fields discarded | Ingest keeps `status`, `active`, `depth_chart_position/order`; daily create-only archive `raw/sleeper-depth-status/YYYYMMDD.json` (point-in-time evidence; the catalog snapshot itself is overwritten) |
| 2 Fantasy workflows | On game days nearly every value is "Unknown/locked"; nothing looked past the current week; waivers had no rest-of-season view; no dedicated player screen | Engine research for this week → Week 18 attached to every QB/RB/WR/TE in the snapshot; ROS waiver research; player detail screen; roster outlook |
| 3 Visual | Developer-console look: repeated slogans and paragraphs, no rail, evidence dumped inline | Shell + Fantasy home rebuilt (below). Still not screenshot-verified against WalterPicks/FantasyPros (no signed-in references supplied) |
| 4 Models | v1 engine's flaws were backups/fringe/moved players (E3 amendment) | Depth/status variant built and captured prospectively beside v1 |
| 5 Markets | Unchanged; still links to legacy pages styled as cards | Open (visual step 3) |
| 6 Cutover | Unchanged | Open |

### Depth/status variant (E3 amendment implemented)

`src/services/projection_depth.py` post-adjusts v1 output (so v1's version and
its prospective cohort are untouched): removes Out/IR/PUP/suspended/NFI and
non-Active players, players whose catalog team differs, and players off a
populated depth chart; only the top active depth-chart QB keeps pass volume
(the next QB inherits it when the starter is out); team targets and carries
are capped at the projected team volume, with vacated volume refilled up to
×1.5. Questionable/Doubtful stay in (participation probability is E3 proper).

Sanity check only — weeks 4–5 of 2026 using *today's* catalog (leaky: it
knows post-game injuries and depth changes), not evidence of skill:

| Week | Pool MAE v1 | Pool MAE depth | QB MAE v1 → depth | Removed but scored |
| --- | --- | --- | --- | --- |
| 4 | 6.09 | 5.27 | 8.97 → 2.49 | 28 of 290 removed |
| 5 | 6.21 | 4.38 | 10.01 → 3.00 | 12 of 255 removed |

The direction and size match the diagnosis (backup QBs and fringe players were
the error). Qualification is prospective only: `capture` now freezes a second
variant under `raw/projection-engine/depth/` (own version: v1 sources +
`projection_depth.py`) whenever a Sleeper catalog with depth fields is at most
two days old; `report(db, "depth")` grades it with the same harness. First
depth catalog arrives with the next daily Sleeper catalog fetch (~00:13 UTC).

### Engine research in the fantasy product

- `projection_engine_serving.py` (scheduled with the 30-minute engine task):
  depth variant over every remaining regular-season game, stored in derived
  checkpoint `projection_engine:research`. Games without a market line use
  each team's mean implied points over its last 8 lined games
  (`team_average_no_line`, labeled in the UI with outlined cells). The nearest
  game per team applies all designations; later weeks only multi-game ones
  (an Out covers one game). First run: 553 players, 170 games, 15 lined.
- `fantasy_decision_models.engine_research` scores it with each league's own
  scoring (ESPN position overrides included) for the selected week, the next
  weeks and ROS over not-yet-started games; stale (>3 h), unresolved, K/DEF
  are explicit statuses, never zero. Reader split into `engine_research.py`
  and registered in `projection_identity.PREDICTION` (the versioned-dependency
  tripwire caught the first attempt). This changes the fantasy prediction
  version, so a new fantasy prospective cohort starts (expected by design).
- Workspace API: `engine_*` fields on every player; `engine_waivers` = top 3
  unrostered per position by engine ROS vs your weakest same-position player.

### Shell and Fantasy screens (visual step 1 + parts of step 2)

- Desktop navigation rail with nested Fantasy tools; mobile sticky header and
  bottom tab bar; compact page header (league · week, freshness badge,
  "Research only" chip); league chips; repeated slogans and paragraphs moved
  into one "Evidence and limitations" disclosure.
- Overview/Today: matchup scorecard (recorded score, provider pregame, engine
  offense total with coverage n/m, starter table with provider and engine
  columns), numbered priorities (now including engine ROS waiver research),
  roster outlook heat table (next 5 weeks + ROS).
- My team: compact roster table (provider, engine this week, next 4 weeks,
  ROS) above lineup review and keeper review.
- Waivers: rest-of-season targets table above the weekly lock-preserving moves.
- Player screen (`tool=player&player=…`): header chips, stat tiles, weekly
  engine bars, evidence list. Reached from every player row.

Verification: 994 backend tests pass (1 skipped), 40 frontend tests,
TypeScript and lint clean; deployed api/worker/evaluation/beat and the
workspace preview.

### Still open in the fantasy area (genuine gaps, not waits)

- FAAB bid ranges: no bid model; league transaction history (`waiver_bid`)
  could support an evidence view of past winning bids — not built.
- Keeper surplus pricing: needs next-season ADP/pick evidence (unchanged).
- Win-probability lineup mode and correlated simulation (E4) and the
  accuracy-weighted Sleeper/engine blend (E5).
- Screenshot-based visual parity with WalterPicks/FantasyPros and browser
  acceptance at phone/desktop widths with keyboard checks (needs Chrome).

## October 12 (later) — E4 simulation, E5 blend, waiver guidance, reference-matched screens, Markets

Owner direction: FAAB and keeper pricing deferred (no league uses FAAB);
waiver guidance, win-probability lineups, correlated simulation and the
Sleeper/engine blend required; visual matching from public screenshots.

### E4 correlated simulation + E5 blend (`fantasy_outcomes.py`, `scripts/fit_fantasy_outcomes.py`)

- Marginals: per position, sd = a + b·mean with empirical standardized-residual
  quantiles (skew and bust mass from data), fitted on 1,191 frozen pre-kickoff
  Sleeper projections graded on platform finals (2026 weeks 2–5).
- Dependence: Gaussian copula with pair-type correlations from nflverse 2025
  residuals — same:QB-WR +0.33, same:QB-TE +0.35, opp:QB-QB +0.20,
  same:RB-RB −0.09, opp:TE-TE −0.13; K/DEF independent (stated).
- Leave-one-week-out checks: p10/p90 coverage 11.1% / 10.8% (target 10/10);
  24 held-out head-to-head matchups: Brier 0.2226 correlated, 0.2230
  independent, 0.25 coin flip — direction right, sample far too small to call
  it validated.
- Blend: the squared-error-optimal engine weights (QB 0.10, RB 0.12, WR 0.07,
  TE 0.20 after shrinkage) did **not** beat Sleeper out of sample with the v1
  engine (MAE 5.881 vs 5.865), so the applied blend is provider-only
  (`blend_status: provider_only_blend_not_better_out_of_sample`). The
  candidate weights are graded prospectively in every engine report
  (`candidate_blend`, weeks after the fit only); the depth variant is the
  likelier winner.
- In the snapshot: win probability vs the opponent, the max-win-probability
  lineup over unlocked slots (chosen on half the draws, reported on the
  other), player p10/p50/p90, boom/bust and a density for charts. Finished
  games enter at recorded platform points; any started-but-unfinished game
  withholds the estimate (no remaining-points model). Model file and module
  are part of the fantasy prediction identity.

### Waiver guidance (`waiver_guidance.py`, no FAAB)

Raw ROS points ranked backup QBs first; replaced by marginal lineup value:
for every remaining week the best offensive lineup is solved with and without
each add/drop, gains summed (byes and unavailability count as zero). Best drop
per add, required K/DEF never dropped, K/DEF streaming from provider weekly
projections (top 3). Tiers by explicit thresholds; Sleeper rolling-waiver
priority and clear days shown. Live: TE upgrades, bye-week QB cover, IR drops.

### Reference-based visual decisions (App Store screenshots, Oct 12)

Sources: WalterPicks iOS listing (id1521523140) and FantasyPros iOS listing
(id1141119371); 12 screenshots reviewed, 6 substantive.

| Reference pattern | Decision |
| --- | --- |
| FantasyPros dark navy surfaces | Adopted: Tailwind `slate` retinted navy app-wide; Fantasy Edge emerald accent kept for identity |
| FP My Playbook quick tiles (Lineup/Waiver/Trade/League) | Adopted on Today: Lineup, Start/Sit, Waivers, Trade |
| FP matchup card with win bar | Adopted: recorded scores + simulated win-probability bar and ranges |
| FP Power Rankings ring + positional bars | Adopted as "League strength" from engine ROS starters (research label) |
| FP rankings Upside/Bust 5-segment meters | Adopted in roster table and player screens from simulated boom/bust |
| WalterPicks "Who do I start?" bars + boom/bust curve | Adopted as the Start/Sit tool, with max-win lineup on top |
| WalterPicks gamelog heat table with "Projected" divider | Adopted on player screen: league-scored results, then engine weeks |
| WalterPicks trade value bars + per-position delta tiles | Not yet built (next) |
| WalterPicks white/blue light theme, photos, AI copy | Rejected: dark theme kept; no player photos (no licensed source); no AI/consensus claims |

### Markets in the shell (visual step 3, first slice)

Native Markets summary: actionable vs research signal counts, ledger counts,
briefing, upcoming signals table (actionable first, exclusion reason on every
research row), then links to full tools. Live: 0 actionable, 258 research.

Verification: 1,007 backend tests (1 skipped), 42 frontend tests, tsc/lint
clean; deployed; release audit matched.

### Overhaul status after this pass

Not complete. Open: trade screen redesign (WalterPicks tiles), native
ledger/parlay screens, Research/Settings native views, prospective
qualification of the depth variant and candidate blend (needs ≥6 graded
weeks), larger win-probability validation sample, phone-width/keyboard
acceptance in a real browser, and cutover (duplicate route retirement).

## October 12 (final) — trade redesign, native Research/Settings/ledger, cutover

### Trade screen (WalterPicks trade value bars + position delta tiles)

`src/services/trade_outlook.py` (request-time, outside the versioned
prediction): for each side the best offensive lineup is re-solved every
remaining week before and after the trade (plus any explicit add/drop plan);
byes and missing engine research count as zero and are named. Output: summed
lineup gain, per-position split by the starting player's position, weekly
gains, and per-player engine ROS points. The trade preview returns it as
`outlook`; `WorkspaceTradeOutlook.tsx` renders value bars, QB/RB/WR/TE delta
tiles and a diverging weekly bar strip above the existing history-based check.
Live example: Zay Flowers for Jahmyr Gibbs → +27.2 / −38.4 lineup points.

### Native Research and Settings

- `GET /api/v2/fantasy/engine-qualification` reads the latest saved prospective
  reports (v1, v1 + Sleeper blend, depth variant) and the win-probability check;
  missing/unreadable reports are statuses, never zeros. Never promotes.
- Research: calibration gates, daily evaluation, NFL lab forecasts, qualification
  progress toward 6 graded weeks, win-probability check, calibration table.
- Settings: service status/alerts, Odds API remaining, provider daily budgets.
- Fixed a live HTTP 500: `/calibration/research` called the now-async live
  calibration handler without awaiting it.

### Win-probability sample now grows prospectively

`src/services/outcome_prospective.py`, run by the 30-minute engine research
task: freezes each league's pregame win probability (only while no starter's
game has begun), then grades the latest pregame capture per matchup once the
NFL week is final and settled (24 h) against the platform matchup snapshot.
Brier vs coin flip is shown on Research. First captures: week 6.

### Cutover

- Every route renders inside the new shell (`WorkspaceNav` in the root layout);
  full tools (Best Bets, Board, Ledger, Parlays, Calibration, Providers,
  Operations, Experiments, Fantasy evidence) highlight their workspace.
- Retired with HTTP 307 redirects (league query preserved): `/` → Today,
  `/fantasy` → My team, `/fantasy/matchup` → Overview, `/fantasy/values` →
  Players, `/fantasy/trade` → Trade, `/nfl-predictor` → Experiments.
- Deleted the legacy fantasy UI (old Nav/FantasyNav, AdviceButton, legacy trade
  calculator/values views) and its Next API proxies.
- Production dashboard gets `FANTASY_WORKSPACE_API_URL=http://api:8000` (the
  main API mounts the same v2 routes); Cloudflare Access gating unchanged.
- Ledger and Parlay screens restyled to the shell (tiles, table, no raw JSON).

### Status

Overhaul complete for the build work. Time-gated only: depth variant and blend
qualification (6 graded weeks), win-probability sample growth. Deferred by the
owner: FAAB, keeper value pricing. Still owner-side: real-browser keyboard and
phone acceptance through Chrome.
