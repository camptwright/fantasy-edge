# Full-stack audit — 2026-09-20

Audit of the live stack on the Mac mini, split into the three product sides:
fantasy, sports betting, and experimental. Every figure below was measured
directly against the running API and the `fantasy-edge-postgres-1` instance
at 02:45 CT on 2026-09-21, not read off the source. Published benchmarks
taken from external literature are marked as such.

Rendered version: https://claude.ai/code/artifact/12f271af-af16-42a9-931d-4a55800c69d9

---

## Live state

Eleven containers: `api`, `worker`, `beat`, `dashboard`, `postgres`, `redis`,
`litellm`, `cloudflared`, `evaluation`, `test-pg`, `grading-preview`. Beat
drives 31 scheduled tasks. 15,901 lines of Python across 76 service modules.

| Store | Rows | Coverage | State |
| --- | --- | --- | --- |
| `player_game_stats` | 3,229,291 | NFL, NCAAF, MLB, NHL, NBA | Healthy — the crown jewel (740 MB) |
| `games` | 9,803 | 5 sports, 2025–26 | NFL & NCAAF stale since 2026-09-15 |
| `player_prop_lines` | 94,348 | 9 sources | Underdog and PrizePicks dead |
| `team_market_lines` | 31,357 | Pinnacle, Bovada, ESPN | 17 days of history only |
| `quote_availability` | 87,460 | All sports | 0 actionable |
| `ledger_bets` | 0 | — | Never used |
| `model_artifacts` | 0 | — | Nothing ever promoted |
| `model_predictions` | 0 | — | Declared ORM table, never written |

`/mnt/data/fantasy-edge/models` is empty. `/mnt/data/fantasy-edge/raw` is
24 GB with no retention policy (14 GB of it in `result-observations`).

---

## F-00 — ESPN rejects every multi-day `dates` range (critical)

`sync_scoreboard` defaults to a nine-day window
(`dates=20260920-20260928`). Probed live during this audit:

```
20260920-20260928 -> 400
20260920-20260927 -> 400
20260920-20260926 -> 400
20260920-20260923 -> 400
20260920          -> 200   (14 events)
```

Ranges fail at every width tested, for both `nfl` and `college-football`,
with and without `limit`. Single dates work. The docstring in
`src/ingest/espn.py` already warned that "ESPN's own range support is
undocumented and unreliable beyond roughly a week" — it is now unreliable
at any width.

**Fix:** loop single dates, the way `scripts/bootstrap_ratings.py` already
does through the same `dates` override.

## F-01 — One sport's failure kills the other two (critical)

`src/scheduler/tasks.py:61` loops `for sport in get_settings().espn_sports`
with no per-sport exception handling, and `nfl` is first:

```python
for sport in get_settings().espn_sports:
    written[sport] = await sync_scoreboard(db, sport=sport)
```

The NFL raise aborts the whole task, so **NCAAF and NBA never run either**.

| Source | Status | Count | Last |
| --- | --- | --- | --- |
| `espn_nfl` | failed | 1,495 (286 in last 24h) | 2026-09-21 02:42 |
| `espn_nfl` | succeeded | 513 | 2026-09-15 21:53 |
| `espn_ncaaf` | succeeded | 513 | 2026-09-15 21:53 |
| `espn_nba` | succeeded | 513 | 2026-09-15 21:53 |

Consequence: **zero upcoming NCAAF games in the database on a September
Saturday.** That is also why `bovada_ncaaf` and `pinnacle_ncaaf` have
written 0 rows for days — there are no games for their lines to attach to.

**Fix:** wrap each sport in `try/except`, record the failure to
`ingestion_runs`, continue the loop.

## F-02 — Nothing alerted, because failure is recorded as data (critical)

`ingestion_runs` faithfully logged all 1,495 failures. `check-data-health`
runs hourly and ntfy alerting was wired up in `cb53286`. Neither fired on a
source that has been 100% failed for two weeks. The threshold is almost
certainly relative ("stale") rather than absolute ("failing").

**Fix:** alert on `status='failed'` streaks and on a `succeeded` run writing
0 rows for N consecutive cycles, independent of staleness.

## F-03 — Scheduled games carry a 0–0 score, not NULL (latent)

242 scheduled 2026 NFL games have `home_score = 0, away_score = 0`. ESPN
returns the string `"0"` for unplayed games and `_apply_scores`
(`src/ingest/espn.py:332`) only nulls on `None` or `""`:

```python
game.home_score = int(home_score) if home_score not in (None, "") else None
```

Current consumers guard on `status == 'final'` (e.g.
`src/api/routers/nfl_predictor.py:78`), and `update_ratings_after_game` is
called behind the `was_final` transition guard, so nothing is corrupted
today. But any future query written as `home_score IS NOT NULL` silently
ingests 242 fake 0–0 finals — the classic shape of a lookahead bug that
surfaces months later in a backtest.

**Fix:** treat `"0"` on a non-final event as absent at ingest.

### Why F-00..F-02 come first

This outage degrades all three sides at once. The betting board has no
NCAAF. Fantasy advice returns `opponent: null` for every player, because
opponents resolve through `games`. The experimental weather lab reports
`unknown_kickoff` for most NFL rows. A meaningful share of what looks like
modeling weakness below is actually starvation.

---

## Side one — sports betting

### Live `/signals` output, all 84 rows analysed

| Measure | Observed | Reading |
| --- | --- | --- |
| Signals returned | 84 | NFL and MLB only — no NCAAF (F-01) |
| Marked `actionable` | 84 / 84 | Hardcoded `"actionable": True` at `sportsbook.py:108` |
| Actionable at negative EV | 50 / 84 | Worst is **−44.65%** |
| EV range | −44.65% … +67.86% | +67% against Pinnacle is a model error, not an edge |
| `model_probability` == baseline | 84 / 84 | The model adds nothing over the baseline |
| Distinct bookmakers | 1 | Pinnacle only — no line shopping |
| `stake_units` populated | 0 | No staking or bankroll layer |

### B-01 — The model is pointed at the wrong opponent (structural)

The commercial +EV industry — OddsJam, Unabated, OddsShopper — all run the
inverse of this pipeline: derive fair value *from* the sharp market (a
no-vig blend of Pinnacle and other market-makers), then hunt that fair value
against soft books. Unabated's entire product is "The Unabated Line," a
curated no-vig blend of the sharpest books.

This app computes an independent Elo probability and looks for disagreement
*with* Pinnacle. Pinnacle's closing line is the most efficient price in the
industry; a −44% or +68% EV against it is overwhelmingly evidence that our
number is wrong.

The soft books are **already ingested**: `parlay_draftkings`,
`parlay_betmgm`, `parlay_caesars`, `sgo_espnbet`, `sgo_bovada`,
`parlay_pinnacle`. Every ingredient for a correct +EV pipeline is in the
database, wired up the wrong way round.

### B-02 — Models that failed their own gate are serving live (critical)

`/calibration`, last evaluated **2026-09-04** (17 days stale):

| Sport | Market | Brier | Log loss | n | Gate |
| --- | --- | --- | --- | --- | --- |
| nfl | moneyline | 0.2348 | 0.6614 | 284 | **false** |
| nfl | spread | 0.2671 | 0.7308 | 284 | **false** |
| nfl | total | 0.2647 | 0.7257 | 237 | **false** |
| ncaaf | moneyline | 0.2222 | 0.6359 | 680 | true |

A coin flip scores 0.25, so the NFL spread and total models are measurably
worse than guessing. They are the models behind the live spread and total
signals. The gate computes a verdict and nothing consumes it.

### B-03 — The player-prop engine produces nothing (critical)

`/props/best` returns `{"items": []}`. `/calibration/coverage` shows
`actionable_quotes: 0` for every stat family across every sport, against
87,460 stored quotes. Blockers are uniform: `unlinked_event` and
`event_not_pregame`.

Props are not being joined to games, so 3.2M rows of result history and 91
distinct Underdog stat types sit unusable behind an identity-resolution
failure. Highest-leverage repair in the codebase.

### B-04 — Two prop sources died silently (high)

| Source | Rows | Last capture | Failures since |
| --- | --- | --- | --- |
| `underdog` | 76,196 (81% of inventory) | 2026-09-07 | 79, since 09-09 |
| `prizepicks` | 5,480 | 2026-09-09 | — |

Underdog is the source whose response shape constraint #17 documents in
detail. Same alerting blind spot as F-02.

### B-05 — The LLM narrative states arithmetically false things (high)

From the live `/recommendations` response:

- *"model probability (0.5663) is lower than the implied probability (0.4255)"* — it is higher.
- *"The expected value (35.78) is lower than the market price (−110)"* — EV percent and American odds are not comparable quantities.
- *"suggesting a unfavorable odds situation"* — attached to a positive-edge selection.

A local 9B model is being asked to reason numerically and is confabulating.
Every number in that narrative is already computed exactly upstream.

### B-06 — No closing-line history, so no way to know if any of this works (high)

`team_market_lines` begins 2026-09-04 — 17 days. `ledger_bets` is empty, so
not one recommendation has ever been recorded and settled. CLV is the
industry's consensus best predictor of long-run profitability, and it is the
one measurement this system currently cannot produce.

### Recommendations

| ID | Action | Impact | Effort |
| --- | --- | --- | --- |
| B-R1 | **Invert the pipeline.** Fair probability becomes a devigged consensus of Pinnacle (plus Circa/BetOnline if added); scan only DK, MGM, Caesars, ESPN Bet for prices beating it. `odds_math.py`'s vig removal — one of the five preserved artifacts — is exactly this tool, currently used for display rather than pricing. Demote Elo to a second opinion that must agree before a bet qualifies. | Decisive | ~2 days |
| B-R2 | **Make `actionable` mean something.** Replace the hardcoded `True` with a real conjunction: positive EV after devig, calibration gate passing for that sport/market, fresh quote, pregame event, Kelly above a floor. On today's data that reduces 84 signals to a handful — the correct answer. | High | Hours |
| B-R3 | **Repair prop↔game linking first.** Instrument `src/ingest/identity.py` and `prop_events.py` to log *why* each match fails, then fix the top cause. Prop backtest, shadow scoring and calibration coverage are all written and waiting on this one join. | Very high | 1–2 days |
| B-R4 | **Template the narrative.** Compute every comparison in Python; hand the LLM a factual skeleton to phrase. Give it the job it is good at instead: summarising the `news_evidence` and `injury_evidence` already archived. | Medium | Hours |
| B-R5 | **Start recording paper bets today.** Ledger schema, settlement flow, `capture-ledger-closes` and CLV maths are all built and idle. Auto-log every qualifying signal with its price and timestamp. In eight weeks there is a real number. | Compounding | Hours |

---

## Side two — fantasy

Measured against the real Sleeper league `2016 Warriors` (12 teams, week 2).

| Field | Value | Reading |
| --- | --- | --- |
| `matchup.status` | `withheld` | No win probability produced |
| `opponent_pregame_projection` | `null` | Yet `/matchup` returns 114.68 for the same opponent |
| `waivers.status` | `withheld_stale_or_started_week` | Waiver engine dark |
| `history_statuses` | 378 / 351 / 157 | candidate / insufficient / unresolved — **57% of pool unusable** |
| `opponent` per player | `null` (all) | Downstream of F-01 |
| `unknown_kickoffs` | 24 | Schedule gaps |

### FF-01 — Two parallel fantasy brains that disagree (high)

`fantasy_decision_models` (v2) is rigorous and withholds almost everything.
`recommendations` is permissive and reports `projection_status: ready` with
full lineup advice. They run over the same league and reach different
conclusions — `/matchup` computes the opponent projection that
`/decision-models` declares unavailable. Duplicated maintenance and
contradictory advice for a single user.

### FF-02 — The optimiser maximises the wrong quantity (structural)

`optimize()` (`fantasy_decision_models.py:65`) uses Hungarian matching over
expected points — the correct algorithm for overlapping FLEX slots, and a
genuinely nice piece of code. But head-to-head fantasy is not a
points-maximisation problem: the objective is maximising P(you outscore your
specific opponent this week). When you are a 20-point underdog you should be
buying variance; when favoured, selling it. An expected-points optimiser is
blind to both.

### FF-03 — Abstention has no fallback ladder (high)

The refusal to invent numbers is the right instinct and worth keeping. But
`status: withheld` plus a paragraph of reasons is, from the user's chair,
indistinguishable from broken. Every commercial competitor degrades
gracefully instead. Rank the options you cannot price.

### FF-04 — The week is behind the slate (medium)

Serving week 2 with `weekly_decisions_open: false` while week 3 kicks off on
the 25th. The advice window is the one the system is closed during.

### FF-05 — 3.2M rows of history feed none of it (opportunity)

351 players marked `insufficient_history` against 3,229,291 rows in
`player_game_stats`. Whatever window the history gate uses is far stricter
than the data available.

### Competitive position

| Capability | FantasyPros | WalterPicks | Fantasy Edge |
| --- | --- | --- | --- |
| Range of outcomes / floor–ceiling | Yes | Yes — core pitch | No — point estimates |
| Matchup win probability | Yes | Yes | Withheld |
| Trade *finder* (proposes deals) | Yes | Yes | `/trade/suggestions` exists |
| Waiver value-added ranking | Yes | Yes | Withheld |
| Expert consensus fallback | 100+ experts | AI consensus | None |
| One-click lineup submission | Yes (Sleeper via extension) | Yes | No |
| Playoff odds simulation | Yes | Yes | No |
| Custom projections from own data | No | No | **Yes — 3.2M rows** |
| Fitted to your exact league scoring | Partial | Partial | **Yes** |

The last two rows are the whole argument for building this. Everything above
them is table stakes we are currently below.

### Recommendations

| ID | Action | Impact | Effort |
| --- | --- | --- | --- |
| F-R1 | **Per-player distributions instead of point projections.** Fit each player a scoring distribution from `player_game_stats` under the league's actual scoring settings (already returned by the API), then Monte-Carlo your lineup against your opponent's. Produces win probability, floor, ceiling, boom/bust and variance-aware start/sit in one pass. Reference implementation: [propsim](https://github.com/pranavcheedalla/propsim). | Transformative | ~1 week |
| F-R2 | **Optimise for P(win), not expected points.** Keep the Hungarian matcher for slot assignment, then evaluate top candidate lineups by simulated win probability against this week's opponent. Surface the delta: *"Starting Nix over Dart: −1.2 projected points, +4.1% win probability."* | High | Depends on F-R1 |
| F-R3 | **Collapse the two engines.** Make `fantasy_decision_models` the source of truth with a confidence band rather than a binary withhold; `/recommendations` and `/matchup` become thin views. | High | ~2 days |
| F-R4 | **Graceful-degradation ladder.** Three tiers instead of a cliff: `modelled` (fitted distribution), `estimated` (positional prior or Sleeper projection, flagged), `ranked-only` (ordinal, no number). Never return an empty screen. | High | ~1 day |

---

## Side three — experimental

The best work in the repository, entirely disconnected from the product.

### The lab model genuinely works

`/experiments/nfl-predictor` runs `nfl_lab_logistic_v1` walk-forward across
four held-out seasons against two baselines. Over n = 1,136:

| Model | Brier | Accuracy | Log loss |
| --- | --- | --- | --- |
| Sharp market line (published benchmark, 2021–25) | ~0.2110 | — | — |
| **Lab candidate — unshipped** | **0.2228** | **63.7%** | 0.6360 |
| Production Elo — what `/signals` serves | 0.2290 | 60.4% | 0.6493 |
| Home-field prior | 0.2472 | 55.4% | 0.6875 |
| Coin flip (reference) | 0.2500 | 50% | 0.6931 |

Beats Elo in all four held-out seasons:

| Season | Candidate Brier | Elo Brier | Candidate acc | Elo acc |
| --- | --- | --- | --- | --- |
| 2022 | 0.2230 | 0.2307 | 61.7% | 59.6% |
| 2023 | 0.2311 | 0.2337 | 62.5% | 59.6% |
| 2024 | 0.2157 | 0.2208 | 66.3% | 62.1% |
| 2025 | 0.2216 | 0.2310 | 64.4% | 60.2% |

Reliability curve is well behaved — 40–60% bucket predicts 0.503 / observes
0.489; 60–80% bucket predicts 0.692 / observes 0.709.

### X-01 — No promotion path from lab to production (structural)

The machinery exists and is well designed: `model_review.py` does paired
bootstrap evaluation with games as the resampling unit, and accepts a
`market_benchmark` argument. Yet `model_artifacts` has **zero rows** and
`model_predictions` is a declared ORM table (`src/models/governance.py:47`)
that **no code in the repository ever writes to**.

The only thing ever deployed — the NCAAF moneyline sigmoid in
`serving_calibration.py` — carries `validation_passed: False` and shipped
via "Explicit user override with baseline retained, 2026-09-05".

### X-02 — Neither model beats the market yet, and that settles the strategy (strategic)

Published walk-forward benchmarks put the closing market line around 0.2110
Brier over 2021–25, with plain Elo around 0.2236. The lab candidate at
0.2228 is better than Elo and **still worse than the closing line**.

That is not a failure — almost nothing beats the closing line — but it does
settle the strategy question: we cannot currently out-predict the market
head-on, which is exactly why B-R1 (price off the sharp market, bet the soft
books) is the right architecture rather than a compromise.

The public state of the art, nfelo, gets there by *regressing its model
toward the market spread* rather than competing with it.

### X-03 — Artifacts written nowhere, grading on a bind mount (high)

`/mnt/data/fantasy-edge/models` is empty. `forecast_grading.grade()` reads
from a filesystem directory rather than the database. `/mnt/data/fantasy-edge/raw`:

```
14G   result-observations
2.6G  forecasts
2.0G  grading
1.6G  mlb_availability
798M  college-player-lab
...   49 directories, 24G total
```

No retention policy. Constraint #18 documents how fragile that mount's
permissions are. Grading history is the most valuable output this system
produces and the least durably stored.

### X-04 — Elo is doing work EPA should be doing (opportunity)

Every serious open-source NFL model built on nflverse uses EPA per dropback
and per carry, success rate, and explosive-play rate as its feature core,
with Elo as one input among many. `src/ingest/nflverse.py` exists and has
not run since **2026-09-04**.

### X-05 — Test suite cannot verify any of this (high)

```
3 failed, 419 passed, 1 skipped, 14 deselected, 179 errors in 29.94s
```

All 179 errors share one cause: the test Postgres on `127.0.0.1:5433` is
missing `quote_availability` — migrations have not been applied to it
(`asyncpg.exceptions.UndefinedTableError`). Three genuine failures remain:

- `test_calibration_foundation.py::test_dedup_query_is_scoped_to_game`
- `test_calibration_foundation.py::test_prop_replay_does_not_load_history_without_linked_quotes`
- `test_ledger_workflows.py::test_verified_clv_sign_and_evidence_gates`

95 uncommitted files, including an untracked migration
`alembic/versions/0017_betting_ledger.py`. Working tree and running
containers have diverged.

### Recommendations

| ID | Action | Impact | Effort |
| --- | --- | --- | --- |
| X-R1 | **Promote the lab model this week.** Write the artifact to `model_artifacts`, persist serving predictions to `model_predictions`, make `/signals` read the promoted artifact instead of calling `moneyline_probability` directly. Keep Elo as retained baseline so `baseline_model_probability` finally means what its name says. | Very high | ~2 days |
| X-R2 | **Add market regression as a feature, not a rival.** Blend model probability toward devigged market probability with a fitted weight, as nfelo does. Composes directly with B-R1 — same sharp-market input, two consumers. | High | ~2 days |
| X-R3 | **Revive nflverse, add EPA features.** Offensive/allowed EPA per dropback and per carry, success rate, explosive-play rate, as rolling leakage-safe windows. The walk-forward harness already exists to judge honestly whether it helps. | High | ~3 days |
| X-R4 | **Make the gate the only door.** No probability reaches `/signals` unless a `model_artifacts` row for that sport and market passes `review()` against both the retained baseline and the market benchmark. Makes B-02 structurally impossible to repeat. | High | ~1 day |
| X-R5 | **Grading into Postgres, raw on a retention clock.** Write graded forecasts to `model_predictions`, keep the filesystem as a raw-evidence cache only, expire `result-observations` beyond a rolling window. | Medium | ~1 day |

---

## The unifying fix — one engine, three products

The three sides are solving the same mathematical problem three times.

- Fantasy needs P(my lineup outscores yours).
- Props need P(this player clears this line).
- The labs need calibrated probabilities to grade.

All three are queries against the same object: **a fitted per-player scoring
distribution.** We have 3,229,291 rows of the exact history required, and
fit none of them.

The primitives are even half-built and quarantined. `sport_distributions.py`
already fits per-sport Gaussian margin and total regressions, and its
docstring says *"This is a shadow candidate; no serving probability is
replaced."* `serving_distributions.py` holds pinned NCAAF distribution
parameters behind a manual approval flag. The machinery exists, applies only
to team markets, and is deliberately prevented from reaching anything.

**Build one `player_distributions` service** that fits a distribution per
player and stat from `player_game_stats` with leakage-safe rolling windows.
Then fantasy samples it under league scoring (F-R1), props integrate its
tail against a book's line (B-R3), and the labs grade it through the
existing harness (X-R1). One service replacing three half-finished ones.

---

## Order of work

| # | Action | Why now | Size |
| --- | --- | --- | --- |
| 1 | Single-date ESPN fetch + per-sport `try/except` | Unblocks NFL, NCAAF, NBA and every downstream side | 1 hr |
| 2 | Absolute-failure alerting in `check_data_health` | Two weeks of silent death must not recur | 2 hrs |
| 3 | Un-hardcode `actionable` | Stop the board recommending −44% EV bets | 2 hrs |
| 4 | Template the LLM narrative | It is currently stating falsehoods | 3 hrs |
| 5 | Migrate test DB; fix 3 real failures; commit the tree | Nothing below is verifiable until this is green | 4 hrs |
| 6 | Paper-log every signal to `ledger_bets` | CLV takes weeks to accumulate — start the clock | 4 hrs |
| 7 | Fix prop↔game linking | Unlocks 87,460 quotes and the whole props stack | 2 days |
| 8 | Promote `nfl_lab_logistic_v1` through the real gate | A better model already exists and is unused | 2 days |
| 9 | Invert to sharp-line pricing vs soft books | The strategic correction; everything else compounds on it | 2 days |
| 10 | Build `player_distributions` | One engine, three products | 1 wk |
| 11 | Fantasy win-probability optimiser on top of it | The feature no competitor can match for this league | 3 days |
| 12 | nflverse revival + EPA features | Consensus feature set; harness already built to judge it | 3 days |

Items 1–6 are roughly a day and a half and restore trust in everything the
system says. Items 7–12 are the build.

---

## Summary

The engineering quality here is high — fork-safe Celery, immutable odds
snapshots, expression-index dedup, a paired-bootstrap evaluation harness,
and a constraint list encoding real production incidents. The problem is not
competence. It is that **the rigour is applied to the lab and the leniency
to production**, which is backwards: the experimental page withholds a model
that works, while the live board hardcodes `actionable: True` on models that
failed their own gate.

Invert that, point the engine at the soft books instead of at Pinnacle, and
fit the distributions we already have the data for.

---

## Sources

**Fantasy**

- [FantasyPros Start/Sit Assistant](https://www.fantasypros.com/nfl/myplaybook/start-sit-assistant.php) · [Waiver Wire Assistant](https://www.fantasypros.com/nfl/myplaybook/waiver-wire-assistant.php) · [Start/Sit FAQs](https://support.fantasypros.com/hc/en-us/articles/115000414827-Start-Sit-Assistant-FAQs)
- [WalterPicks feature set](https://apps.apple.com/us/app/walterpicks-fantasy-football/id1521523140)
- [Fantasy Math](https://nathanbraun.com/fantasymath/) — players as explicit probability distributions
- [RotoWire Trade Analyzer](https://www.rotowire.com/football/article/fantasy-football-trade-analyzer-find-and-grade-redraft-fantasy-football-trades-in-2026-134904) · [ffwrapped playoff simulator](https://ffwrapped.com/fantasy-football-playoff-odds-calculator)

**Sports betting**

- [Unabated — finding positive-EV wagers](https://unabated.com/post/finding-positive-ev-wagers-step-by-step-guide)
- [OddsShopper — best +EV software 2026](https://www.oddsshopper.com/articles/comparisons/best-sports-betting-software) · [SmartStake comparison](https://www.smartstake.app/learn/best-ev-betting-software)
- [Closing line value explained](https://www.pinnacleoddsdropper.com/blog/closing-line-value) · [VSiN on CLV](https://vsin.com/how-to-bet/the-importance-of-closing-line-value/) · [ProbWin CLV guide](https://en.probwin.com/guides/closing-line-value-clv-ultimate-metric-measure-your-edge/)

**Experimental / open source**

- [nfelo — market regression to improve NFL prediction accuracy](https://www.nfeloapp.com/analysis/using-market-regression-to-improve-prediction-accuracy-in-the-nfl/)
- [propsim](https://github.com/pranavcheedalla/propsim) — Monte Carlo player-prop engine with multi-season backtesting
- [Carlosgjr08/nfl-predictor](https://github.com/Carlosgjr08/nfl-predictor) · [mitch-avis/nfl-predictor](https://github.com/mitch-avis/nfl-predictor) · [aryan123197/nfl_predictions](https://github.com/aryan123197/nfl_predictions)
- [nflverse](https://github.com/nflverse) · [FiveThirtyEight nfl-elo-game](https://github.com/fivethirtyeight/nfl-elo-game) · [nfeloqb](https://github.com/greerreNFL/nfeloqb)
- [mfradkin2/sports-predictions](https://github.com/mfradkin2/sports-predictions) — grade every published prop, bias-correct at n ≥ 30
- [georgedouzas/sports-betting](https://github.com/georgedouzas/sports-betting) — scikit-learn wrapper with value-bet backtesting
