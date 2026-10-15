# Engine v2 plan: merging the two research tracks (draft, 2026-10-15)

Status: planning. Nothing here is built. Engine v1, its prospective record
and the decision-model cohort (`1c14c946116d`) stay untouched: v2 is a new
recipe in new modules, and no PREDICTION module changes before week 11.

## The two research tracks

**Track A (external review, 2026-10-15)**, a prioritised list of additions
and a test method:

1. opportunity quality (goal-line/red-zone/end-zone opportunity, xTD, xFP);
2. role changes (snap share, share changes, teammate absences, practice);
3. receiving depth (air yards, aDOT, air-yard share, short/deep mix);
4. team play selection (pass rate over expectation, neutral tendencies, pace,
   dropbacks vs attempts);
5. QB rushing detail (designed runs, scrambles, kneels, goal-line);
6. context-adjusted efficiency (CPOE, RYOE, YACOE, pressure);
7. opponent and lineup context.

Method: separate candidates against the retained baseline, rolling-origin
holdouts, identical cohorts with coverage reported, stat-level and
league-scored errors, prop calibration, slices by position/week/workload.

**Track B (this repo, `docs/2026-10-12-engine-research.md`)**: the
pre-registered 2023-2024 holdout, the advanced-stats test and the gap
anatomy.

## Where they agree, and where each corrects the other

| Point | Track A | Track B evidence | Merged position |
|---|---|---|---|
| Items 1-3 as extra inputs | Top priority | Tested as a correction layer: +0.004 (CI +/-0.015) on Sleeper, -0.019 (CI -0.044, +0.006) on the engine | They hold no extra information *in aggregate*. Still worth one structural test each where they target a specific stat (TD, rec yards) or the disagreement slice, not as general features |
| Routes | Not live; don't label snaps as routes | Track B's route proxy used nflverse participation, which has no 2026 data | Track A is right. Route features are research-only; the null result means little is lost |
| Evaluation split | Rolling origin | Track B used leave-one-season-out (2025 trained the 2023 model) | Track A is right. All v2 work uses rolling origin |
| Metrics | Per-stat errors, prop log loss | Fantasy points only | Track A is right. Add both |
| Team denominators | Possibly distorted | 13 whole 2025 games dropped, 2026 under 1% partial | Real but small. Fix it first anyway, since it is cheap and every share depends on it |
| Where the gap is | Not addressed | Agreement set at parity. The gap lives in disagreements and weeks 1-4, not injuries or teammate absences | Prioritise what explains disagreement and the early season |
| Items 4-7 | Proposed | Untested | Test them, in the order below |
| Paid tracking feeds | Don't buy before testing | Agree | No purchases |

What neither track listed, and the gap anatomy points to:

- **The offseason prior.** Weeks 1-4 carry half the gap. The engine starts
  each season from last season's shares, without knowing about team changes,
  rookies' draft capital, depth-chart moves or a new play caller.
- **Anchoring.** The engine underestimates players Sleeper newly ranks as
  starters by 2.7 points, and holds fading roles too high. That is a
  speed-of-update problem in the share model (EWMA half-life 2 games plus
  shrinkage), separate from which features it reads.
- **Ensembling.** On the agreement set the two are equal, and their
  disagreements are informative, so a learned blend is the likeliest route
  to beating Sleeper. A blend tested earlier gained ~0.02. Adding a third,
  market-based source (prop-implied means) is untested.

## Workstreams, in order

Each one is kept only if it improves the rolling-origin dev score against
the current v2 candidate, at the stat level and in league-scored points,
without losing coverage.

**W0. Harness (`scripts/engine_lab.py`), before any model work.**

- Rolling origin by week: each test week sees only games before its
  earliest kickoff. 2023 is burn-in; 2024-2025 are graded. 2022 stays sealed.
- One frozen cohort: player-weeks with a Sleeper projection and a stat
  line. Coverage is reported per candidate, and a missing projection counts
  as missing, never as zero.
- Metrics:
  - league-scored MAE (symmetric pool, week-cluster CI);
  - per-stat MAE (targets, receptions, yards, TDs, attempts);
  - team-level MAE for pass attempts, carries and plays;
  - p10/p90 coverage.
- Slices: position, weeks 1-4 vs 5-18, workload tier, agree/engine-only/
  Sleeper-only.
- Data: nflverse feeds that are live in 2026 (pbp, ff_opportunity, PFR snap
  counts, FTN charting, NGS, injuries, all through week 5 on 2026-10-15).
  Participation is excluded.

**W1. Team denominators.**

- Team totals come from team-level play-by-play (attempts, carries,
  dropbacks, plays) instead of summing snap-linked players.
- Unlinked players fall back to their weekly roster team.
- Backfill the 13 unlinked 2025 games.
- Measure the change in team-volume and share error. Expected effect is small.

**W2. Offseason prior (largest measured gap).**

- Week-1 shares come from last season's shares, adjusted for:
  - departed and arrived teammates' vacated targets and carries
    (`rosters_weekly`, trades);
  - draft capital for rookies (`draft_picks`);
  - preseason depth-chart rank (nflverse depth charts; the depth variant's
    code paths).
- The prior's weight decays with games played this season.
- Graded on weeks 1-4.
- Variant needing your call: Sleeper's season-long projection as a prior.
  It is strong, but it makes the engine less independent of its baseline.

**W3. Role-change speed (the disagreement slice).**

- PFR snap share (live) as a leading indicator of target and carry share.
- Change-point or two-speed updates: a shift in snap share speeds up the
  share model's adaptation.
- Teammate-absence redistribution is in scope, but the anatomy says it is
  not where the gap is.
- Graded on the engine-only and Sleeper-only slices first, then overall.

**W4. Opportunity quality, structurally (Track A #1).**

- Replace historical TD rates with expected TDs per opportunity from
  field-position shares (inside the 20, 10 and 5; end-zone targets) and
  ff_opportunity xTD, shrunk toward the position rate.
- Graded on TD error, and on anytime-TD log loss against archived 2026
  prices where available.

**W5. Team play selection (Track A #4).**

- Neutral-situation pass rate over expectation (nflfastR xpass), pace
  (seconds per snap, neutral plays per game) and sacks plus scrambles
  (dropbacks vs attempts) feed the volume regressions.
- Graded on team-level volume error first.

**W6. QB rushing detail (Track A #5).**

- Split QB carries into designed runs, scrambles and kneels from pbp.
- Project designed runs and scrambles separately; drop kneels.
- QBs carried the largest engine bias (+2.2) in the holdout.

**W7. Receiving depth (Track A #3).**

- aDOT and air-yard share feed yards per target, not volume.
- Graded on receiving-yards error. Track B's null result makes this a
  low-expectation test.

**W8. Efficiency (Track A #6).**

- CPOE, RYOE and YACOE from NGS, with heavy shrinkage (more early in the
  season).
- Expected gain is small.

**W9. Opponent context (Track A #7).**

- Opponent-adjusted yards and TDs allowed per opportunity.
- Must beat the information already priced into the spread and total.

**W10. Ensemble.**

- Per-position blend of v2, Sleeper and, for 2026 only, de-vigged prop
  means.
- Weights are learned rolling-origin from trailing graded accuracy and are
  allowed to depend on agreement, week and workload.
- This is what would actually serve decisions if it beats Sleeper.

## Qualification

1. Development: W0-W10 on 2023-2025 rolling origin. These results are
   exploratory, since many candidates are tried.
2. Confirmatory: freeze v2 and the blend, register a protocol (metric, pool,
   pass bar) in the research doc, commit it, then run once on 2022.
   Caveat: its coefficients would be fit on later seasons.
3. Prospective: v2 runs as a new recipe in 2026 prospective capture beside
   v1. Serving promotion only through the existing gate (6 graded weeks,
   symmetric pool, CI excluding zero).
4. Decision models switch only after that, and not before week 11.

## Expectations

On the agreement set the engine is already at parity, and the gap to
Sleeper is about 0.08 points per player. A realistic target is engine
parity, and a blend that beats Sleeper by a small but measurable margin,
concentrated in weeks 1-4 and role changes. No accuracy figure is promised
before testing.

## Decisions needed

- May W2 use Sleeper's season-long projection as a prior?
- When to spend the sealed 2022 season: once, for the frozen v2 plus blend.
- Confirm no decision-model changes before week 11, so the current cohort
  can finish.
