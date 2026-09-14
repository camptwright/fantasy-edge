# NFL reserve-budget player props

Enabled with user approval September 8, 2026 (Central). The production reserve
is 10 credits; the example configuration retains the conservative default 50.

`ODDS_API_NFL_PROPS_PRIORITY=true` makes the existing 30-minute team-market
task prioritize NFL player props instead of paid team-market polling across
sports. Free Bovada/Pinnacle polling is unaffected. The four requested markets
are passing yards, rushing yards, receiving yards and receptions, from FanDuel
only. This is partial coverage, not all NFL props or all bookmakers.

The normal task requests only the nearest matched pregame NFL event within
two hours of kickoff. A manual commissioning probe may pass `horizon_hours=48`.
It shares season/pacing and account quota state, uses a request lock, reads
current quota headers from the free events endpoint and checks the maximum
four-credit cost before the event-odds request. Missing quota information fails
closed. Other consumers of the same API key can still reduce the external
balance; the local guard cannot reserve credits in the provider account.

Quotes require fresh provider market timestamps and a unique exact canonical
NFL player name, with a team consistency check when a current team is known.
Ambiguous and unknown players are parked. No synthetic player IDs or fuzzy
matching are used. Only paired over/under main lines are accepted. Successful
snapshots withdraw missing offers only for the selected event/book/markets.
Provider failures leave old quotes subject to their unchanged 45-minute TTL.

The small reserve budget cannot support continuous all-week coverage. Prices
from the commissioning probe will become stale before tomorrow's game; the
near-kickoff task must succeed to make those offers eligible again. Do not
promote model candidates or relax freshness based on this integration.

Official API contract: https://the-odds-api.com/liveapi/guides/v4/

## Commissioning result — September 9, 2026 02:49 UTC

The authorized probe consumed four credits (44 to 40) and wrote 30 lines
for Patriots–Seahawks: 11 receiving-yard, 11 reception, six rushing-yard,
and two passing-yard lines. The API returned 27 eligible baseline predictions.
Jadarian Price's three lines stayed excluded for insufficient history.
The NFL/player Best Bets page returned HTTP 200 and rendered the new feed.
A second invocation returned zero without changing quota telemetry, confirming
pacing prevented another paid call. Twenty-three focused offline tests passed.
These are eligible quotes, not 27 distinct recommended bets, and this check
does not certify model calibration, player availability or future feed uptime.
