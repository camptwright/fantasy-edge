# Engine v2 plan: merging the two research tracks (draft, 2026-10-15)

Status: v2 (lean) built, failed its registered 2022 test, and captured prospectively as research since 2026-10-15 (week 6). Owner approved the build 2026-10-15. Engine v1, its prospective record
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

## Decisions (owner, 2026-10-15)

- W2 may use Sleeper's season-long projection as a prior: yes.
- The sealed 2022 season is spent once, on the frozen v2 plus blend: yes.
- No decision-model (PREDICTION module) changes before week 11: confirmed.

## Sleeper archive leakage (found 2026-10-15)

Sleeper's historical weekly endpoint (`/v1/projections/nfl/regular/{season}/{week}`)
is not a pre-game record. It absorbs in-game news after kickoff.

- **2026 weeks 2-5 against the projections this app froze before kickoff**
  (`fantasy-prospective/provider-weekly`, 1,606 player-weeks, both Sleeper
  leagues' scoring):
  - the endpoint's values miss actual points by 4.28 on average, against
    5.78 for the frozen copies;
  - its changes since the freeze correlate +0.46 with the outcome;
  - this holds for every capture lead time.
- **2021-2025 archive:** among RB/WR/TE with no injury designation who had
  played 70%+ of snaps in each of their previous two games:
  - those who then left a game early (<30% of snaps) had that game's
    projection cut by more than half 22% of the time (108 cases);
  - those who played normally had it cut 0.3% of the time (4,024 cases).
  - This shows in every season.

Consequences:

- Every historical engine-vs-Sleeper comparison in
  `docs/2026-10-12-engine-research.md` (the registered holdout, the
  advanced-stats test, the gap anatomy) graded against a Sleeper baseline
  that holds some post-kickoff information. Those gaps overstate Sleeper's
  pre-game edge by an unknown amount. Comparisons between this app's own
  models (v2 vs v1) are unaffected.
- Inputs: Sleeper projections for the game being projected are never a v2
  input, historically or live. Projections for games already played
  (last week's, and week 1's from week 2 on) are allowed. Their
  contamination is past information, and live serving reads the same
  archive, so lab and serving see the same thing.
- A clean Sleeper comparison exists only where this app froze Sleeper's
  numbers before kickoff: 2026 onward.

## Development results (2026-10-15, `scripts/engine_lab.py`)

Graded 2023-2025, rolling origin by week, symmetric starter pool,
week-cluster bootstrap, 2016 Warriors scoring. 2022 is never graded.
Negative means the first model is better.

| Configuration | vs v1, identical rows | vs Sleeper archive (leak-advantaged) | Blend vs Sleeper archive |
|---|---|---|---|
| core (v1's inputs as ridge stages) | +0.043 (+0.008, +0.079) | +0.187 | |
| core + offseason | +0.004 | +0.065 | |
| core + role speed | +0.007 | +0.072 | |
| core + availability | -0.007 | +0.047 | |
| core + opportunity, team play, QB rush, depth, efficiency or opponent | +0.038 to +0.047 | +0.165 to +0.189 | |
| all groups | -0.076 (-0.118, -0.030) | -0.014 (-0.065, +0.033) | -0.059 (-0.094, -0.026) |
| **lean** (core, offseason, role, availability, previous-week Sleeper) | **-0.074 (-0.117, -0.029)** | **-0.018 (-0.066, +0.027)** | **-0.055 (-0.087, -0.024)** |

Other findings:

- A gradient-boosted share stage instead of ridge scores +0.016 against the
  Sleeper archive, versus ridge's +0.007 on the same groups. No gain, so
  the stages stay numpy ridge, which the serving image can run.
- MAE rewards the median; the best per-position median shift gains ≤0.02.
  Not applied.
- An earlier run that fed Sleeper's projection for the game itself scored
  -0.063 against the archive. That is the leak, so it is discarded.
- Opportunity quality, play selection, QB rushing detail, depth of target,
  efficiency and opponent context each add nothing on top of core (Track A
  items 1, 3-7), confirming the advanced-stats result. The gains come from
  the offseason prior, faster role updates and who is available this week:
  the gap anatomy's two findings.

2026 weeks 2-5 against Sleeper frozen before kickoff (clean baseline, about
550 pool rows, only 4 week clusters, so the intervals are rough):

| Comparison | all | lean |
|---|---|---|
| v2 vs frozen Sleeper | +0.032 (-0.141, +0.172) | +0.026 (-0.122, +0.150) |
| v1 vs frozen Sleeper | +0.165 (-0.035, +0.349) | |
| v2 vs v1 | -0.156 (-0.179, -0.137) | -0.133 (-0.148, -0.100) |
| 50/50 blend vs frozen Sleeper | -0.069 (-0.173, +0.015) | -0.060 (-0.176, +0.025) |

Frozen design: **lean**. It needs no play-by-play, so serving can build it
from data the app already ingests plus nflverse release CSVs.

## Registered test (2026-10-15, before any 2022 run)

Spends the sealed 2022 season once, as approved.

- **Model:** `src/services/projection_engine_v2.py` and `scripts/engine_lab.py`
  as committed with this section, configuration `lean`, constants as
  committed (RIDGE 10, HALF_LIFE 2, PLAYER_GAMES 12, TEAM_GAMES 8). No
  change after this commit.
- **Data:** nflverse 2019-2022 and Sleeper's archived weekly projections. v2
  refits every week on games before that week's first kickoff (training
  rows from 2020 on), so no later season informs 2022.
- **Comparators:**
  - v1 (`projection_engine.py` DEFAULT, nflverse history 2021-2022) on
    identical rows;
  - the Sleeper archive (leak-advantaged, so a conservative bar);
  - the blend rule as committed (per position and phase, a v2 weight
    learned on earlier weeks' out-of-sample rows from 2021 on).
- **Metric:** paired absolute error on the symmetric pool (top 12/24/30/12
  QB/RB/WR/TE by either side), 2016 Warriors scoring, week-cluster
  bootstrap with 4000 draws, seed 0.
- **Pass bar, all four required:**
  1. v2 minus v1: pooled CI upper < 0.
  2. v2 minus Sleeper archive: pooled CI lower ≤ 0 (not significantly worse).
  3. Blend minus Sleeper archive: pooled CI upper < 0.
  4. No position where v2 is significantly worse than v1 (CI lower > 0).
- **Reporting:** the result is reported whatever it is. A pass opens the
  prospective track only: v2 serves decisions only after 6 graded
  prospective weeks against frozen Sleeper, and no decision-model change
  before week 11.

    .venv/bin/python -m scripts.engine_lab confirm --scoring warriors_scoring.json --out lab --configs lean

### Registered test result (2026-10-15, run once after the registration commit 20c2da0)

**Failed: two of four conditions.**

| Condition | 2022 result (95% CI) | Met |
|---|---|---|
| 1. v2 minus v1 < 0 | -0.020 (-0.106, +0.056), 1,579 pool rows | no |
| 2. v2 not significantly worse than the Sleeper archive | -0.033 (-0.126, +0.059) | yes |
| 3. Blend minus Sleeper archive < 0 | -0.051 (-0.107, +0.006) | no |
| 4. No position significantly worse than v1 | QB -0.06, RB -0.07, WR +0.03, TE -0.01; none significant | yes |

- Every pooled difference points the same way as in development, but v2's
  gain over v1 is a quarter of the development estimate (-0.020 vs -0.074).
- Weeks 1-4 carry it: -0.134 vs v1 (weeks 5-18: +0.014). The offseason
  prior is the part that replicates.
- By position against the Sleeper archive: QB -0.41 (significant), RB
  -0.12, WR +0.19 (significant), TE -0.04. The blend gains significantly at
  QB and RB and loses at WR.
- One difference from development, noted after the fact and not used to
  excuse the result: 2022's models train on two prior seasons, against up
  to five in development.

What it means: v2 is **not confirmed**. It does not serve decisions, and
"beats v1" or "beats Sleeper" is not claimed. It is captured
prospectively as a research track beside v1 and the depth variant,
against Sleeper frozen before kickoff. That is the only clean test left.
Any v2 change from here is a new version with its own prospective
record.

## Serving (2026-10-15)

- `projection_engine_v2_data` builds records and features for both the lab
  (nflreadpy) and the worker (nflverse release CSVs, cached under
  `raw/nflverse-v2-cache`).
  - On 2026 rows, serving predictions equal the lab's exactly.
  - Peak memory is 511 MB. A first attempt that held whole CSVs was killed
    at the worker's 1.5 GiB limit.
- `fantasy.projection_engine_v2` runs every 3 hours on the evaluation
  queue.
  - It freezes forecasts at their first capture inside the 72-hour window
    (create-only files under `projection-engine/v2/forecasts`).
  - It grades them as variant `v2` against Sleeper frozen before kickoff
    (6 graded weeks required).
  - First run: 2 games, 64 forecasts, 27.5 s, version `7eeb6fd0…`.
- Never served. The decision-model cohort is unchanged (`1c14c946116d`).
- Changes after the registration commit, none to the model:
  - streaming and memory work;
  - an opponent leak in the refactored availability features, caught by
    comparing against the registered code and covered by a regression test;
  - duplicate Sleeper IDs now resolve to the entry that is projected to play.

  With these, the lab's development figure moves from -0.074 to -0.075. The
  registered result stands as produced at 20c2da0.
- The earliest possible owner review is after 6 graded prospective weeks:
  weeks 6-11, so late November.
