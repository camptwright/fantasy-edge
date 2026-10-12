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
