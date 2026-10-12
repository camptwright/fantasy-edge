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
