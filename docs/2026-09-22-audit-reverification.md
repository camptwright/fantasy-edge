# Audit reverification — 2026-09-22

Second independent check of [the 2026-09-20 audit](2026-09-20-full-stack-audit.md),
following [the 21 Sep check](2026-09-21-audit-reverification.md). Everything
below was measured against the running containers and Postgres at 21:35 CT.
Today's remediation docs were read, but I didn't take their claims as proof.

Rendered version: https://claude.ai/code/artifact/12f271af-af16-42a9-931d-4a55800c69d9

**10 of 19 fixed, 6 partial, 3 open** (B-04 deferred at the user's request).
On 21 Sep it was 7 fixed, 2 partial, 10 open.

## Repo state caveat

No commits since `9d5ee8e`. The working tree has 12 modified files, 14 new
source/test files and 7 new docs. I diffed each changed `src/` file against
the running `api` container. Most are deployed. These five are **not**:
`fantasy_simulation.py`, `fantasy_decision_models.py`,
`fantasy_prospective.py`, `sleeper.py` and the new
`fantasy_component_history.py`. All were edited at 16:58, 11 minutes after
`2026-09-22-fantasy-final-verification.md` was written, so no verification
covers them. The deployed simulation keys history by `week`; the working
tree keys it by `(season, week)`.

My test run: 646 passed, 1 skipped, 20 deselected and 15 errors. All the
errors were `Another DB test is active`: a concurrent run held the test
database's advisory lock. Codex processes were running. I didn't rerun or
change anything. The team reports 657 passing.

## Status

| ID | Status | Live evidence |
| --- | --- | --- |
| F-00 – F-03 | Fixed | ESPN: 35 syncs per sport in 6 h, one transient failure each at redeploy |
| B-01 | **Partial** (was open) | `sharp_pricing.py` + `/markets/price-comparisons`: 296 fresh quotes, **0 comparisons** |
| B-02 | Fixed | 0 actionable signals |
| B-03 | Partial | Event binding + roster corroboration; no approved prop model |
| B-04 | Deferred | At user's request; Underdog last data 09-07, PrizePicks 09-09 |
| B-05 | Fixed | Deterministic summaries |
| B-06 | **Partial** (was open) | `paper_ledger.py` + `/api/v1/ledger/coverage`; `ledger_bets` = 0 |
| FF-01 | **Fixed** (was open) | recommendations / matchup / decision-models share one simulation block |
| FF-02 | **Partial** (was open) | Opponent-aware lineup simulation built; withheld on 4 players |
| FF-03 | **Fixed** (was open) | `fallback_rankings` with `estimated` tier |
| FF-04 | **Fixed** (was open) | Week 3, `weekly_decisions_open: true`; projections 128.34 vs 121.74 |
| FF-05 | **Partial** (was open) | League-scored history drives distributions; pool 185/31/48 |
| X-01 | Partial | `model_artifacts` 0, `model_predictions` 0 |
| X-02 | Open | No market blending |
| X-03 | Open | Raw archive 28 GB (24 GB on 09-20, ≈2 GB/day); models dir empty |
| X-05 | Fixed (team-reported) | See test caveat above |

X-04 (nflverse / EPA revival) is an opportunity rather than a defect; still
untouched. nflverse last wrote on 2026-09-04.

## Why the new capabilities output zero

**B-01.** The engine is the design the audit asked for: devigged Pinnacle,
Circa or BetOnline references against exact-contract DraftKings, FanDuel,
BetMGM, Caesars or ESPN Bet prices. It returns nothing because:

- `/markets/price-comparisons` reads only `TeamMarketLine`
  (`sportsbook.py:584`). Team-market sources are Pinnacle, Bovada and ESPN,
  and none of them is in `TARGETS`.
- The Odds API is the only team-market feed that carries target books.
  Redis `odds_api:quota_status` shows `used: 488, remaining: 12`, unchanged
  since 2026-09-13. `ODDS_API_NFL_PROPS_PRIORITY=true` in `.env` also makes
  `poll_team_markets` return 0 for every sport before any request. The task
  "succeeds" every 30 min in about 20 ms and writes no `ingestion_runs` row.
- Prop inventory already has `parlay_pinnacle` alongside
  `parlay_draftkings`, `parlay_betmgm` and `parlay_caesars`, but the
  comparison doesn't read it. The Pinnacle prop feed is thin: 293
  observations, last seen 2026-09-21.

**B-06.** Only `actionable: true` signals can enter the ledger, and none
exist. The audit recommended logging every signal. Actionable-only is
stricter, but no CLV evidence builds up until a model is approved, even
though that evidence would be one of the main reasons to approve one.

**FF-02.** All four win-probability blockers are specialists: Aubrey (K, 2
scored weeks), Bates (K, 2), BAL DST (2) and GB DST (1). The simulation
requires 8 samples per player (`fantasy_simulation.py:15`). With
current-season history only, full-lineup win probability can't appear
before about week 9. The undeployed `(season, week)` change looks like
prior-season support, which is the right direction.

## Remaining work, in order

1. **Commit, deploy and verify the working tree once.** The repo, the
   containers and the docs currently describe three different states.
   Wait until the other editor has finished.
2. **Give B-01 inventory.** Extend the comparison to prop lines, which is
   cheap and uses data that's already collected. Decide on team-market
   target books: wait for the Odds API reset, upgrade the plan, or add a
   source. Revisit `ODDS_API_NFL_PROPS_PRIORITY`.
3. **X-01.** Persist `nfl_lab_logistic_v1` to `model_artifacts`, record
   serving predictions, and run the paired baseline + market review.
4. **Start collecting CLV now.** Add a shadow cohort for research-tier
   signals, flagged as never actionable, so the closing job measures CLV
   before any approval.
5. **FF-02 specialists.** Finish multi-season history, or add a labelled
   K/DST-only positional prior.
6. **X-03 retention.** Expire `result-observations` on a rolling window;
   keep durable grading results in Postgres.
7. **X-02 / X-04.** Market blending, nflverse revival and EPA features,
   evaluated prospectively.
8. **Backlog.** B-04 (deferred), shared `player_distributions` for props
   (the fantasy empirical-residual engine is a start), and the typed-model
   Phase 0 spike (not started; no code references Jev or Laya).
