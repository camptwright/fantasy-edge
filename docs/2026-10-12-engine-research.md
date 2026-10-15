# Engine research: what the leading services do, and what we adopted (2026-10-12)

Scope: every engine in the app — team/game projections, player projections,
fantasy lineups, waivers, trades, betting (team markets and player props),
and the experimental labs.

Method: each service's approach was reconstructed from what it publishes —
methodology pages, open-source code, papers and public data APIs — then
re-implemented here and tested walk-forward on data it never saw. Apps were
not decompiled and private endpoints were not used: that breaches their terms
and would not produce anything we could validate. A method was adopted only
when it beat what we serve on held-out data; otherwise it is recorded below.

## Team and game projections (and team-market betting)

**Services:** FiveThirtyEight NFL Elo (published methodology), nfelo (open
source, `greerreNFL/nfelo`; read for method, no code copied — the repo has no
license), Silver Bulletin ELWAY, ESPN FPI.

**Their method:** a points/Elo rating updated from game results with a
margin-aware (log-scaled) update; offseason reversion toward the mean; home
field, rest and QB adjustments; nfelo adds "market resist" (update harder
when the closing line beat the model) and regresses the model's line toward
the market with a logistic curve in disagreement.

**Built:** `src/services/team_model.py` (shared math), `team_model_serving.py`
(live replay from the fitted end-of-2025 ratings), artifact
`config/nfl_team_model.json` from `scripts/research_game_model.py`.

**Evidence** (nflverse closing lines; fit 2006–2014, test 2015–2025, 3,028 games):

| Model | MAE | Brier |
|---|---|---|
| Previous serving Elo | 10.55 | 0.2326 |
| Rebuilt model | 10.14 | 0.2212 |
| Closing market | 9.81 | 0.2128 |
| Rebuilt, regressed to market | 9.83 | 0.2135 |

No against-the-spread edge at any disagreement threshold. **Adopted** as the
NFL baseline for moneyline/spread research probabilities (regressed to the
consensus spread), the Markets "game projections" and power ratings, and the
fantasy engine's environment for weeks without a line. Actionable status is
unchanged: it still needs version-bound validation. NCAAF stays on Elo
(nflverse has no college data).

**Vig removal** (`scripts/research_devig.py`, 5,358 closing moneylines):
multiplicative, additive, power and Shin are within 0.0001 log loss;
multiplicative slightly under-forecasts heavy favourites (81.2% vs 82.0%
won). Not worth changing the preserved method for two-way NFL markets.

**Sharp-reference pricing** (OddsJam/Unabated's published approach: compare
each book to the no-vig sharp consensus) was already implemented in
`sharp_pricing.py` — no change.

## Player projections

**Services:** FantasyPros (consensus of many sources, accuracy-weighted;
published accuracy method), PFF / ESPN (Mike Clay) / WalterPicks / Yahoo
(volume → share → efficiency models), Sleeper (licensed from RotoWire),
4for4 (opponent-adjusted fantasy points allowed).

**Opponent adjustment** (`scripts/research_projection_features.py`): defense
efficiency allowed by position, shrunk, as a multiplier. Held-out 2026 pool
MAE 5.821 → 5.814 (choice on 2025 only). Consistent but tiny — Vegas totals
already carry most of it. **Not adopted** (would reset the engine's
prospective record for ~0.1%).

**Consensus** (`scripts/research_projection_consensus.py`, 2026 weeks 2–5,
764 pool rows, all scored with the same league rules):

| Source | Pool MAE |
|---|---|
| Sleeper | 5.91 |
| ESPN | 5.92 |
| Mean of Sleeper + ESPN | 5.89 |
| Mean of all three | 5.77 |
| Engine v1 | 5.70 |

The engine's settings were partly tuned on these weeks, so this is optimistic.
**Adopted** prospectively: ESPN projections are frozen pregame
(`espn_projections.py`) and graded against Sleeper beside the engine; an
equal-weight consensus is graded the same way (Research tracks). Player screens
show ESPN and consensus as research columns. Decisions still use Sleeper until
a track qualifies.

## Fantasy lineups

Win-probability lineups from the correlated simulation (prior work) already
follow the industry approach. The simulation's mean stays provider-only until
the blend or consensus qualifies prospectively.

## Waivers

**Services:** Sleeper/FantasyPros "most added", FantasyPros waiver assistant.
**Adopted:** Sleeper's public 24-hour trending adds (`sleeper_trending.py`),
shown beside the lineup-value guidance as crowd context; it never ranks.

## Trades

**Services:** FantasyCalc (values from real trades; public API), KeepTradeCut,
WalterPicks/FantasyPros analyzers (value chart + team impact).
**Adopted:** FantasyCalc market values per package beside the rest-of-season
lineup impact in the trade outlook. Found and fixed a scheduler bug that had
left the daily FantasyCalc (and nflverse stats, snaps, schedule) collection
idle since 2026-10-08: beat lost its schedule on every redeploy.

## Player props

**Services:** Outlier, BettingPros prop analyzer, Unabated prop tools
(projection + distribution vs the de-vigged line).
**Experiment** (`scripts/research_prop_model.py`; same 2026 props, all weeks):

| Stat | Serving history model | Engine + empirical spread | No-vig market |
|---|---|---|---|
| Receptions (954) | 0.2657 | 0.2600 | 0.2485 |
| Receiving yards (938) | 0.2657 | 0.2589 | 0.2498 |
| Rushing yards (452) | 0.2917 | 0.2751 | 0.2507 |

(Brier.) Every model is worse than a coin flip at the line; the market is best.
**Adopted** as a research comparison only: `prop_engine.py` +
`config/prop_engine_distribution.json`, `/props/engine-board`, Markets "engine
vs market" table. The serving prop path (with its own calibration and
validation) is unchanged.

## Experimental labs

The NFL predictor lab blends 0.75 lab / 0.25 market and is under prospective
review (46 forecasts). Everything above says the market should carry more
weight (nfelo's own optimum and our regression floor of ~0.85 on the market).
Changing the recipe would reset its prospective record, so this is a
recommendation for the owner's review rather than a change.

## Sources

- FiveThirtyEight NFL methodology: https://fivethirtyeight.com/methodology/how-our-nfl-predictions-work
- nfelo market regression: https://www.nfeloapp.com/analysis/using-market-regression-to-improve-prediction-accuracy-in-the-nfl/
- nfelo about and code: https://nfeloapp.com/about, https://github.com/greerreNFL/nfelo
- FantasyPros accuracy methodology review: https://support.fantasypros.com/hc/en-us/articles/115002204827
- Combined projections vs single sources: https://www.r-bloggers.com/2013/03/comparing-espns-cbss-and-nfl-coms-fantasy-football-projections-using-r/
- nflverse data: https://github.com/nflverse/nfldata
- Sleeper trending endpoint (community docs): https://pkg.go.dev/github.com/dsheehan167/go-sleeper@v0.2.0
- FantasyCalc: https://fantasycalc.com (values API used under its terms)

## Update 2026-10-13

**NFL lab:** blend moved to 85% sharp market / 15% lab (the team model's
fitted market-regression floor, chosen independently of the lab's results),
graded from each frozen record's stored lab and market probabilities, so the
existing cohort is reused. The 25% blend stays as a comparison.

**Team scoring split** (`scripts/research_totals_model.py`): offense/defense
point ratings. Test 2015–2025: total MAE 10.71 vs 10.95 for the serving
running averages (market 10.44); over/under Brier 0.257 vs 0.264. The serving
fit defers to the market total when one exists. Used for NFL totals, team
points in projections, and the fantasy engine's unlined weeks.

**College model** (`scripts/research_ncaaf_model.py`, ESPN history via
`scripts/fetch_ncaaf_history.py`, 8,634 FBS games 2016–2025): same math with
program-anchored offseason reversion (the SP+/FPI preseason practice) and a
low rating for first-seen (mostly FCS) teams. Test 2021–2025 Brier 0.170 vs
0.1995 for the serving Elo; market 0.139. NCAAF moneyline/spread keep the
owner-approved calibration override and carry the model as a research field;
NCAAF totals use it. Known gap: neutral-site games are not flagged in the
games table, so home field applies to bowls.

**UI (Chrome review of FantasyPros' web tools):** adopted the Multi-League
Assistant idea as an "All leagues" Today view, and four-player Start/Sit.
Browser audit at 390 px: no sideways overflow on any page, the mobile bar
stays pinned while scrolling; fixed focus rings and 24 px link targets.
Not yet adopted: FantasyPros' post-game recap and "Rate My Team".

**Data fixes found on the way:** bye/out starters blocked pregame
win-probability capture; ESPN sync never refreshed games left unfinished
outside its rolling window (now re-polled).

## Update 2026-10-13 (signed-in FantasyPros review, 2016 Warriors)

Reviewed My Playbook: Dashboard (standings, avg points, playoff odds,
position radar, weekly points vs median, start/sit accuracy, team insights),
Matchup (slot-by-slot, current vs optimal), Waiver Central (position ranks),
Trade Finder, League Analyzer (team/positional/starter ranks), Post-Game.

Adopted: trade finder (win-win one-for-one trades), position ladder on
Waivers, slot-by-slot matchup board with hindsight-optimal lineup and
start/sit accuracy (our week 4: 81.7%; FantasyPros: 82%), season tiles and a
League tool with standings and simulated playoff odds (2016 Warriors 99.9%;
FantasyPros: 99%), bye-week plan-ahead review items. Remaining schedules are
now stored for both platforms.

Then adopted (2026-10-13, later): "Are they playing?" (designation, bye,
game-linked report, game state per starter), League Analyzer team rankings
with starter-slot and bench ranks, a Post-game recap (result, league rank,
all-play, bench points left, superlatives; season all-play, expected wins,
luck, weekly points vs league median chart), and strength-of-schedule stars
(half-PPR points allowed by position, quintiles of remaining schedules) on
waiver guidance and the position ladder. Every review item is now built.

## Player props and parlays (2026-10-13)

Reference methods (public descriptions): OddsJam/Unabated value finding
(de-vig each book, average into a fair price, compare the best available
price; Pinnacle is not treated as uniquely sharp for props because it often
does not post them), Props.Cash/Outlier context (L5/L10/season/vs-opponent
hit rates, D vs Pos), and book same-game pricing (FanDuel has modelled SGP
correlation since 2019, so multiplying legs misprices them).

Adopted: a prop board refreshed every 10 minutes (no-vig consensus at the
main line, best price per side, EV, hit rates, D vs Pos, engine P(over)),
and a tracker that freezes +3% EV picks with 3+ books when first seen,
closes them at the last pre-kickoff consensus (CLV) and grades them. The
parlay generator lets the local model (llama3.2:3b via LiteLLM, 1–5 s on
the M4) parse the request only; every field must be grounded in the text
and slate, because the model invented players and sides in testing. A
deterministic optimizer builds the best parlay per book.

Same-game correlation: Spearman correlation of season-centred residuals by
relationship and position:stat, from 2025 player-games (466 pairs, n >= 150,
shrunk by n/(n+200)). For example, WR receptions vs receiving yards is 0.72,
and QB passing yards vs a teammate WR's receiving yards is 0.22. On 2026
holdout pairs with |rho| >= 0.15, a Gaussian copula beat independence (Brier
0.2004 vs 0.2087; all pairs 0.1501 vs 0.1506). Correlation is never scored
as value, because books reprice correlated legs, so same-game parlays get
fair odds only.

Also: games now carry ESPN's neutral-site flag, so the team models drop home
field for bowls, the College Football Playoff and international NFL games.

## Update 2026-10-14

**Market-implied projections** (BettingPros/WalterPicks "Vegas" projections;
`scripts/research_market_projection.py`). Each prop's no-vig consensus at the
main line was turned into a stat mean (bisection on P(over); Poisson for
counts, normal with a 2025-fitted CV for yards) and moved into each source's
stat line, weights fitted leave-one-week-out. 2026 weeks 2–5, 767 pool rows,
341 with a 2+ book market:

| | Pool MAE | Rows with a market |
|---|---|---|
| Sleeper | 5.955 | 6.277 |
| Sleeper + market | 5.942 | 6.248 |
| Consensus (Sleeper, ESPN, engine) | 5.804 | 6.082 |
| Consensus + market | 5.816 | 6.110 |

At the stat level the market mean beats Sleeper on rushing yards (16.1 vs
17.7 MAE) and ties elsewhere, but the paired fantasy-point gain for Sleeper is
−0.03 (95% CI −0.11 to +0.05) and the consensus gets worse. Sleeper (RotoWire)
and ESPN already price in the lines, and touchdowns, which drive most of the
scoring variance, have no multi-book anytime-TD market here. **Not adopted.**
The prop engine's empirical ratio distribution overstates a starter's
rushing mean by ~11 yards when inverted (it was fitted across all players);
it is still correct for the use it was fitted for (P(over) from the engine's
mean).

**Harness repairs found on the way:**
- The prospective engine report raised `UnboundLocalError` on its first graded
  row (a function-local import shadowed `offensive_weights`), so from the
  moment week 5 became gradeable every later step of the task — ESPN freezes,
  trending, strength of schedule, win-probability capture — stopped. Fixed;
  steps now run independently and report their own errors, and
  `tests/test_lint_guard.py` fails the suite on any pyflakes F821/F823.
- Week 5 props: on 2026-10-11 the disk was full; each paid ParlayAPI call
  succeeded and then failed writing its raw archive *before* ingesting, so the
  day's 24 credits bought nothing. Ingest now runs first and the archive is
  best-effort. The 8 daily calls also went to MLB (4–8 a day) and one London
  game; they are now reserved for NFL kickoff slots (one per later slot, at
  most three per slot while later slots wait), and other sports use only what
  is left.

**Full-pool grading** (`src/services/sleeper_pool.py`). The rostered-player
harness grades ~25–40 rows a week. FantasyPros grades projected top-N ∪ actual
top-N per position, which includes unrostered players. Sleeper's full weekly
stat projections (already stored by the sync) are now frozen for every
QB/RB/WR/TE in the 3 hours before kickoff, and engine v1, ESPN and the
consensus are graded against them on box-score results with each league's
rules, using the same promotion check. Shown as "Full pool" tracks on
Research; first captures at week 6's Thursday game.

**Injury designations → play probability** (plan Phase 3;
`scripts/research_availability.py`, `config/availability_rates.json`).
nflverse weekly injury reports (final game status and practice participation)
joined to PFR snap counts, regulars only (≥ 40% of offensive snaps over the
previous three games; without that filter, healthy backups who never take a
snap read as "did not play" — most Questionable QBs). Fit 2016–2023, test
2024–2025 (731 designated regular player-weeks):

| Model | Brier |
|---|---|
| Rule lineups use (Questionable plays, Doubtful/Out do not) | 0.164 |
| P(play \| status) | 0.113 |
| P(play \| status, practice) | 0.108 |
| P(play \| status, practice, position), shrunk | 0.104 |

Regular Questionable players played 68% of the time in 2024–2025 (full
Friday practice ~90%, limited ~75%, no practice ~50%; Questionable QBs with a
limited week 48%); Doubtful ~1%. **Adopted for display:** "Are they playing?"
shows "Q · 78%" with the practice note, Start/Sit shows a risk-adjusted
projection, from the platform designation plus this week's practice status
in nflverse's current-season report (refreshed every 3 hours). Lineup and
waiver decisions and the versioned prediction are unchanged.

## Update 2026-10-14 (later): anytime-touchdown prices

Question: would collecting anytime-TD props from several books cost more?
ParlayAPI bills a flat 3 credits per `/props` page regardless of markets,
bookmakers or rows (parlay-api.com/docs), with `limit` up to 10000. One 3-credit
probe (through the normal daily reservation) returned the whole of week 6 in a
single page: 738 rows, `x-result-has-more: false`. So the existing NFL call now
also requests `player_anytime_td` and passing TDs, with `limit` 5000, at no extra
cost. The Odds API (FanDuel) bills per market, so FanDuel TD props are not added.

- Anytime TD: DraftKings 310 and Caesars 339 rows, Yes side only; Pinnacle 9
  rows with both sides; BetMGM none. ParlayAPI says not to derive a missing No
  price, so these are not offers: `src/services/td_market.py` freezes them
  create-only under `projection-engine/market-td/quotes` for research, outside
  `player_prop_lines` and every betting path. 602 of 658 week-6 rows matched a
  game and player (the rest are unmatched names).
- Hold on the Yes side, against Pinnacle's no-vig price for the 9 overlapping
  players: DraftKings' implied probability is a median 1.07x fair (range
  1.04-1.10), Caesars 1.10x (1.06-1.15). Small, single-week sample.
- Passing TDs (`player_pass_tds`, `player_passing_touchdowns`,
  `player_touchdown_passes`) are two-sided at all four books and now flow into
  the normal priced-offer pipeline as `passing_touchdowns`.

Next: after week 6 is graded, re-run the market-implied projection research with
TD probabilities (Yes price divided by the book's hold, possibly scaled so a
game's expected TDs match its implied total) replacing the projection's TD term.

## Update 2026-10-14 (evening): error decomposition and the depth variant

Week 6 had not been played (first game Thursday Oct 16), so this used
2025 weeks 4-18 and 2026 weeks 1-5 walk-forward. Every comparison below is
on the promotion gate's pool (top-N by Sleeper's projection or by actual,
per position-week), one league's scoring, week-block bootstrap CIs.

**Where engine v1 stands** (`scripts/diagnose_projection_engine.py`,
`scripts/research_fixed_pool.py`): pool MAE 5.83 vs Sleeper 6.04 in 2025
(paired CI -0.29 to -0.13) and 5.93 vs 6.18 in 2026 (-0.40 to -0.07; 2026 is
in-sample for the engine's tuning). Ahead at every position, least at QB.

**Tried and rejected:**
- Off-role share leak (QBs pulled toward a 3% target share, WRs/TEs toward a
  ball-carrier's carry share: +0.46 points a game for QBs): removing it
  improves all-player MAE (5.06 -> 5.00) but worsens the pool (2026 +0.02 to
  +0.05): the leak was offsetting under-projection of starters.
- Role-anchored share priors (shrink toward the player's own 8/16-game role
  instead of a position prior): all-player MAE 5.06 -> 4.77, pool worse in
  every setting (CI vs default all above 0). The heavy shrinkage is right for
  the players who matter for lineups.
- Engine/Sleeper blend: weights chosen on 2025 (0.6-1.0 engine) give 2026
  5.933 vs engine 5.939 (CI -0.04 to +0.04). Nothing to add.
- Tuning harness flaw found: `tune_projection_engine.evaluate` picks each
  variant's pool by that variant's own projections, so variants are graded on
  different players. The fixed-pool scorer is `research_fixed_pool.py`;
  DEFAULT params were chosen on the old pool and have not been re-searched.

**Adopted: depth/status variant rules rewritten** (`projection_depth.adjust`,
behind the workspace's engine research column and the depth capture track).
It had been captured prospectively only (26 forecasts, none graded) on the
belief no historical depth charts exist. nflverse publishes daily depth-chart
snapshots, weekly roster status and final injury reports, so
`scripts/research_depth_backtest.py` now reproduces its inputs walk-forward:
- Old rules: worse than plain v1 by 0.17 (2025, CI 0.10-0.23) and 0.21 (2026,
  CI 0.11-0.34). The team-volume cap scaled starters down whenever stale
  players stayed on a team; only the depth-one QB passed.
- Removals (IR, moved team, off chart) alone: no change for players who played.
- Passing an Out/Doubtful player's targets and carries to teammates in
  proportion: share 0.75 chosen on 2025; 2026 -0.03 (CI -0.06 to -0.01).
- QB: backups pass nothing only when the depth chart's top available QB also
  started the last game (or that starter is ruled out); a ruled-out starter's
  volume goes to the top remaining QB. Costs ~0.1 on graded QBs (relief
  appearances) but stops backups showing a starter's line (week 6 before:
  several backups at 11-17 points).
- Net: level with plain v1 (+0.01, CI -0.05 to +0.03; -0.03, CI -0.07 to
  +0.02), 0.18-0.24 better than the old rules. Week 6 research projections
  changed for every player; starters the cap held down rose (Malik Nabers
  10.2 -> 15.6, Sleeper 14.0), backups fell to ~2-3, Chicago's Keenum/Bagent
  split stays open because the chart and the last start disagree.
Engine v1's version (and its prospective record) is unchanged; the depth
variant's version changes.

## Pre-registered holdout test of engine v1 (registered 2026-10-15, before any run)

Why: the promotion gate needs six graded prospective weeks, and that takes
until late November. Retrospective evidence can never satisfy the gate, but a
test on seasons the engine never saw can say now whether v1 is likely to pass.
This section is committed before the holdout script exists or runs; the git
timestamp is the proof of order. Nothing below may change after results are
seen. Any later engine change is a new model that needs a new holdout.

- **Model under test:** `projection_engine.compute` with `DEFAULT` params, the
  blobs `src/services/projection_engine.py` 7b2fbe3 and
  `src/services/game_environment.py` 93c65ba (commit f5cb628). No refitting.
- **Holdout:** 2023 and 2024 regular seasons, weeks 1-18. Neither season was
  used in development: tuning and every diagnosis used 2025 W4-18 and 2026
  W1-5, and the DB holds no 2023/2024 stats.
- **Inputs, all pregame from public data:** nflverse weekly player stats
  (2022-2024; walk-forward, each week sees only earlier games) and nflverse
  schedules (spread_line, total_line). Those are closing lines, which the live
  engine never sees; this is a small information advantage for the engine and
  is reported as a caveat.
- **Comparator:** Sleeper's weekly projections for the same weeks from the
  public API (`/projections/nfl/regular/{season}/{week}`), as served today.
  Whether they equal Sleeper's kickoff snapshot cannot be verified; a caveat.
- **Scoring:** the 2016 Warriors league (1398509004950376448) rules, for both
  sources and the actuals.
- **Graded rows:** players who played (an nflverse stat row) with both an
  engine and a Sleeper projection for that game. Availability is not graded.
- **Primary metric:** paired MAE difference (engine - Sleeper) on the
  FantasyPros pool (top 25 QB / 50 RB / 60 WR / 20 TE per week by Sleeper
  projection, union top-N by actual), the pool used for every earlier figure.
  95% CI by week-block bootstrap (4,000 draws, seed 0).
- **Secondary:** the promotion gate's pool (top 12/24/30/12 by Sleeper
  projection only), per position, per season.
- **Pass bar, fixed now:** pooled 2023+2024 CI upper bound below 0; the point
  estimate below 0 in each season separately; no position with a CI lower
  bound above 0 (significantly worse). Anything else is reported as a fail.
- **Fidelity check, run first:** the same nflverse loader on 2025 W4-18 must
  reproduce the DB-based result (engine 5.83, Sleeper 6.04) within 0.10 MAE.
  If it does not, the loader is wrong and the holdout is not run until the
  cause is fixed; the fix and its reason are documented here.
- **Status:** retrospective evidence, labelled as such. It does not count
  toward the prospective gate and does not change `serving_promoted`.

### Holdout results (2026-10-15, `scripts/research_holdout.py`)

Fidelity check passed: the nflverse loader on 2025 W4-18 gives engine 5.807 /
Sleeper 6.035 (DB-based: 5.83 / 6.04), 2,859 rows.

**Registered verdict: PASS.** FantasyPros pool, 2023+2024, 6,797 rows, 36 weeks:
engine 5.779 vs Sleeper 5.937, difference -0.158 (CI -0.209 to -0.107);
2023 -0.161, 2024 -0.155; QB -0.22, RB +0.02 (CI -0.08 to +0.13), WR -0.22,
TE -0.31. No position significantly worse.

**But the pass does not mean what it appears to.** The registered pool adds
the top-N by *actual* points, which rewards whichever source projected the
boom weeks. Two pools that never look at the outcome:

| Pool (2023+2024) | Engine | Sleeper | Engine - Sleeper (95% CI) |
| --- | ---: | ---: | --- |
| Registered: Sleeper top-N ∪ actual top-N (25/50/60/20) | 5.779 | 5.937 | -0.158 (-0.209, -0.107) |
| Gate (secondary): Sleeper top 12/24/30/12 | 6.586 | 6.523 | +0.063 (-0.012, +0.134) |
| Exploratory: Sleeper top-N ∪ engine top-N (12/24/30/12) | 6.534 | 6.437 | **+0.097 (+0.027, +0.164)** |

On the outcome-free symmetric pool the engine is significantly *worse*: RB
+0.21 (CI +0.07 to +0.36) and WR +0.14 (+0.02 to +0.25); QB -0.11 and TE
-0.02 are not significant. 2025 W4-18 agrees (+0.092, CI -0.03 to +0.21). On
that pool the engine is biased: QB +2.2 points, RB -1.6, WR -0.8, TE -1.7;
Sleeper is within 0.9 at every position.

So every earlier "engine beats Sleeper" figure in this document, which used
the actual-inclusive pool, overstated the engine. Among the players a lineup
decision is about, Sleeper is the better projection.

Repairs tried, development seasons only (2023-2025; 2022 kept sealed):

- Parameter grid (half-life 2/4/8, share prior games 0.5/1.5, share quantile
  0.5/0.75, rate scale 1/2/4; 36 settings): best +0.066, none at parity.
- Per-position affine recalibration, leave-one-season-out: worse
  (+0.10 to +0.17); MAE rewards the median and the fit corrects the mean.
- Per-position engine/Sleeper blend, leave-one-season-out: -0.022, +0.001,
  -0.018, every CI spanning zero. The engine adds at most ~0.02 points per
  player as a second opinion.

Changes made as a result:

- The prospective promotion check now grades top-N by Sleeper's *or* the
  challenger's projection (`projection_engine_prospective.starter_pool`),
  never the outcome. This is stricter for the engine and was chosen after
  seeing these results, which is why it can only make promotion harder.
- No engine change; v1's version and its prospective record are untouched.
  Decisions keep using Sleeper's projections, which this test supports.
- 2022 (Sleeper and nflverse both available, 2021 as history) stays sealed for
  the next engine with a structural change, under a protocol registered first.

## Do advanced usage stats help? (2026-10-15, `scripts/research_advanced_stats.py`)

Exploratory, development seasons only (2023-2025 W1-18 graded, 2022 used as
history and never graded, so it stays sealed). 16,814 player-weeks with an
engine projection, a Sleeper projection and a stat line.

Added to the box-score usage the engine already reads (targets, carries,
attempts, team shares, trailing points), all trailing and strictly before
kickoff: nflverse expected fantasy points rescored with league scoring (xFP)
and points minus xFP; snap share and a route proxy (on field on a dropback,
from nflverse participation); targets per route; air-yard share; aDOT; WOPR;
red-zone target/carry and goal-line carry shares; last-game snap/route share
and snap trend. Coverage: snap/route 100%, xFP 98%, aDOT 79%.

Method: residual corrections trained leave-one-season-out, same learner with
and without the advanced set, graded on the symmetric starter pool (top
12/24/30/12 by either source), week-cluster bootstrap. Two learners:
absolute-error gradient boosting, and per-position Huber linear models.

Paired MAE difference (negative = the advanced set helps), points per player:

| Comparison | Boosting | Linear |
|---|---|---|
| Sleeper + box correction, adding advanced | +0.004 (-0.011, +0.019) | +0.013 (-0.003, +0.029) |
| Sleeper + advanced correction vs raw Sleeper | -0.005 (-0.039, +0.031) | +0.007 (-0.034, +0.048) |
| Engine + box correction, adding advanced | -0.019 (-0.044, +0.006) | +0.011 (-0.013, +0.035) |
| Engine + advanced correction vs raw Sleeper | +0.110 (+0.047, +0.173) | +0.136 (+0.074, +0.196) |
| Raw engine vs raw Sleeper (same rows) | +0.076 (+0.019, +0.131) | |

Findings:

- The advanced stats carry no measurable information beyond box-score usage
  and Sleeper's projection. The confidence intervals are narrow (about
  ±0.02 points per player), so this is a tight null, not an underpowered one.
- They do not close the engine's gap to Sleeper. The gap (~0.08-0.14) is not
  missing usage detail; the likeliest source is what RotoWire knows before
  kickoff that no box score shows: injuries and practice reports, inactives,
  depth-chart and coaching changes, news.
- Single-stat signal agrees: no feature's Spearman correlation with Sleeper's
  miss exceeds 0.10 at any position. The largest are TE last-game route share
  and snap trend (~0.10): Sleeper reacts slowly to TE role changes. The
  boosted engine correction gained 0.10 at TE (-0.164, -0.038), the linear
  one 0.05 (CI touching zero). That is the only lead, and it is post hoc.
- xFP is the best single trailing predictor of next-week points for QB, and
  roughly ties trailing actual points elsewhere, as the practitioner
  literature claims. But the engine already captures the same volume.

Decision: do not add these stats to the engine or the decision models. The
next engine work, if any, should target pre-kickoff information (injury
designations, practice participation, inactives) rather than more usage
detail. It would be tested on the sealed 2022 season under a newly
registered protocol.
