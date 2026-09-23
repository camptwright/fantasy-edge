# Strategic audit implementation

## First increment: B-01

The Odds API team parser previously discarded all but the first book and
stored it under an anonymous provider label. New observations retain each
book's identity; old generic observations are not retroactively relabelled.
Polling quota guards and the NFL-prop-priority setting remain unchanged.

`GET /markets/price-comparisons` compares fresh pregame soft-book prices
against exact-contract, two-sided devigged sharp references. Brands count
once even when multiple providers carry them. References and targets must
be observed within five minutes; opposing legs within one minute. Different
handicaps, integer push markets, missing prices and anonymous books fail
closed. Reference quote IDs and timestamps accompany every comparison.

This is a research endpoint, not a promotion or replacement of serving
probabilities. It does not claim any listed book is accessible in Texas.
No bets are placed and no existing identity or approval gate is relaxed.

## Remaining sequence

1. B-01: capture and grade these comparison cohorts prospectively, add the
   comparison dashboard and approved strategy serving adapter. Verify live
   target-book coverage within existing provider budgets.
2. X-01/X-03: persist version-bound lab artifacts and predictions in
   Postgres, then evaluate promotion against paired retained and market
   baselines. A historical Elo win is not market-beating evidence.
3. B-06: paper-ledger capture and verified closing-contract matching.
   Missing historical observations cannot be manufactured or backdated.
4. FF-01–FF-05: unify fantasy decision views, explicit fallback tiers,
   upcoming-week selection, player-history diagnostics, then scoring
   distributions and opponent-aware win-probability optimization.
5. B-04: provider health and supported replacement coverage; do not scrape
   PrizePicks or mislabel replacement feeds as a recovered direct API.
6. X-02/X-04: leakage-safe market blending and nflverse/EPA candidates,
   prospectively evaluated without promising they beat the market.

The independent review document remains untouched.

## Verification

Full isolated-database regression suite: 641 passed, one intentional skip,
20 live tests deselected. New offline tests cover source preservation,
target exclusion, duplicate-brand references, exact handicaps, push holds,
and asynchronous quote rejection. No paid feed requests were triggered.
