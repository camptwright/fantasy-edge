# SportsGameOdds and ParlayAPI — initial integration

Both keys are loaded from the root `.env` using `SPORTSGAMEODDS_API_KEY` and
`PARLAY_API_KEY`. Header authentication keeps credentials out of URLs. No paid
upgrade was made. `AGGREGATE_PROPS_ENABLED=false` disables both new collectors.

## Scope and budget

The `fantasy.sync_aggregate_props` task checks eligibility every five minutes. It requires a known
scheduled kickoff within 24 hours, then reserves budget atomically
before each request. Failed requests consume the reservation. Provider 401/402/403/429
responses suspend that provider for 24 hours. The direct Underdog beat entry was
removed; The Odds API collector and budget remain unchanged.

SGO polls all five supported sports (NFL, NCAAF, MLB, NBA, NHL); Parlay remains
limited to its verified NFL/NCAAF/MLB mappings. NBA includes core counting stats,
three-pointers and supported combinations; NHL includes goals, points, assists,
shots on goal, blocked shots and saves. Hockey's provider `points` means goals;
`goals+assists` maps to hockey points. Total shots never map to shots on goal.
Mappings follow https://sportsgameodds.com/docs/data-types/stats and existing
result-ingestion names. Offseason sports are wired and fixture-tested, not claimed
live-validated without actual offers. Shared caps are unchanged, so wider coverage
does not imply unlimited or complete-slate polling.

Ingestion summaries now distinguish competing main lines, outside-window/unknown
kickoff offers, and unresolved identities or non-scheduled games. These remain
parked instead of bypassing matching or model eligibility checks.

Official ESPN, MLB and NHL score/status schedules refresh every five minutes.
Final-only player-result ingestion and correction handling remain separate;
the model reads completed eligible history. This is live game-state ingestion,
not a validated in-play player-prop pricing model. Partial boxscores are not
inserted as final outcomes, and pregame forecasts remain immutable.

- SGO: at most 60 locally reserved event objects/day; one event per call, no pagination.
- Parlay: at most 24 locally reserved credits/day; three per request, no pagination.
- Each provider/sport has a 25-minute minimum pacing slot; the collector has a shared lock.
  This decouples beat timing from the reservation and avoids alternate-cycle skips.
  SGO polls within 12 hours before kickoff; Parlay within two hours to preserve its
  scarce daily credits. Daily caps, failed-attempt charges and freshness rules remain unchanged.
- Initial credential probes consumed one SGO event request and three Parlay credits
  before the local counters were installed. Provider telemetry remains authoritative.

The free-tier ceilings deliberately limit coverage. These are not whole-slate,
all-market integrations. Changing the daily settings requires reviewing the account
allowance. The status route `/calibration/prop-provider-status` shows configuration,
book ownership, local reservations and last provider response without keys.

## Price and identity safety

Initial bookmaker ownership is disjoint: SGO handles Bovada and ESPN BET; Parlay
handles DraftKings, BetMGM, Caesars and Pinnacle; existing The Odds API handles
FanDuel. This avoids presenting the same book through multiple providers. Source
labels retain provider and bookmaker, such as `sgo_bovada`.

Only paired full-game O/U offers at the same line are ingested. Both sides need
valid American prices and timestamps within 15 minutes at intake. SGO requires
both sides available. Parlay requires explicit false DFS-normalization flags.
No fair/consensus price or synthetic DFS price is used as a sportsbook price.

Player identity uses an exact unique canonical name within the sport and a
provider-reported fixture matched to existing teams/kickoff. Conflicting known
player teams are rejected; missing current-team fields remain unknown. No fuzzy
player matching, invented provider IDs or fabricated kickoff times are used.
Multiple competing lines for a main-line slot are parked.

Quote observation time remains the time we actually observed it. Availability
ages from the older source price timestamp, not the polling time. Repeated/older
snapshots cannot refresh an offer. The normal 45-minute serving TTL still applies.
Raw payloads and receipt times are archived under `aggregate-props`. Partial
responses do not trigger whole-feed withdrawal; existing offers expire normally.

## Initial live result — September 9, 2026

After resolving compatibility with unset canonical current-team fields, fresh saved
responses produced 37 SGO NFL observations and 20 Parlay NFL observations. No
additional provider requests were needed for that reprocessing. The live endpoint
then returned 84 qualified NFL offers:

- The Odds API / FanDuel: 32
- SGO / ESPN BET: 18; SGO / Bovada: 16
- Parlay / Pinnacle: 15; DraftKings: 2; Caesars: 1

Counts change with freshness, injury gates and kickoff. MLB had no actionable
offers from this initial sample; NCAAF had no kickoff inside the window.

Concurrent validation (three rounds, concurrency three) passed the populated NFL
prop route at 0.201s measured p95, Best Bets at 0.600s, Recommendations at 0.778s,
and Calibration at 1.244s. No partial-page or HTTP errors were detected. Atomic
quota checks against isolated Redis keys verified first-request allowance,
duplicate-request rejection and daily-budget rejection.

## Deliberately unfinished

- Wider MLB/NCAAF coverage and additional prop families need live fixtures and
  mapping validation. SGO's ambiguous generic strikeout stat is not enabled.
- DFS ingestion/entry-level payout evaluation is not enabled. Current requests
  select sportsbook sources only, even though the parser explicitly rejects DFS
  flags. This is not a restored direct Underdog connection.
- SGO is limited to one event and Parlay to 1,000 rows per request. Neither is
  claimed as complete-slate coverage. Unknown names/fixtures are parked.
- Account-wide SGO remaining allowance is not supplied in the observed response
  headers; local counters are not represented as an authoritative account balance.

References: https://sportsgameodds.com/docs/endpoints/getEvents and
https://parlay-api.com/docs . The user-supplied SGO reference was also used.

## Pacing/visibility deployment — September 10

The five-minute eligibility/25-minute pacing change, narrower request windows,
Board prop section, and two-sided recommendation narrative ranking are implemented
and deployed with explicit local-preview mode after user approval. The separate
preview publishes only 127.0.0.1:13000, checks loopback Host and rejects Cloudflare
forwarding headers and cross-origin requests. Never route a public tunnel to this
local-mode container: Host checks alone are not a network security boundary.
The remote Compose dashboard has local mode disabled and fails closed without
CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD. Server-side dashboard reads now send the
API token; the preview deployment copies it from the API without printing it.
Existing Parlay credits already
spent today are not reset by these changes. Best Bets' combined top 30 can rank
team bets above props; its Player props filter isolates them.

Verified after deployment: Board, Best Bets (player filter), Recommendations and
Calibration returned 200 without partial-data warnings. Local preview rejected
nonlocal Host and Cloudflare forwarding headers with 403; anonymous API returned
401. Remote dashboard returned 503 (Access configuration missing, not bypassed).
Live counts were 74 NFL and 73 MLB offers; other sports awaited qualifying quotes.
28 backend regression tests and the dashboard production build passed.

## Mapping and model research update — September 9, 2026

SGO now maps `receiving_receptions` to receptions and explicitly maps MLB
`batting_hits`, `batting_totalBases`, and `pitching_strikeouts`. Generic and batter
strikeouts remain excluded. Football passing attempts, completions, touchdowns,
interceptions, and rushing attempts are also mapped; normal identity, freshness,
history and availability gates still determine whether an offer is usable.

Forecast capture includes two frozen, research-only recipes: market consensus and
a 75% retained-baseline / 25% market blend. They require two other bookmaker brands
at the exact same player/game/stat/line, paired no-vig prices seen within 15 minutes,
and exclude the target bookmaker. Distinct brands are not assumed independent.
No serving probabilities change. Insufficient fresh overlap produces no candidate.

The September 10 00:04 UTC evaluation found no settled new-feed NFL evidence.
The older MLB opportunity-count candidate had Brier 0.20937 versus baseline
0.21441 across 22 games, but its game-clustered improvement interval crossed zero.
Recent-normal candidates were worse on both MLB and NCAAF. These results do not
justify promotion; candidate-outcome totals must not be described as unique bets.

The guarded 00:08 UTC refresh wrote 91 NFL and 76 MLB observations. Its immutable
00:08:22 UTC capture contained 215 qualified player forecasts and 42 eligible
offers for each market recipe, all market comparisons from one NFL game. These
are correlated offers, not 42 independent games or evidence of improved accuracy.

A later three-round concurrent live check at 03:50 UTC found 75 NFL and 36 MLB
actionable props with no validation errors. Observed p95 was 0.228s NFL, 0.266s
MLB, 0.597s Best Bets, 0.800s Recommendations, and 1.090s Calibration. NCAAF
player props remained awaiting live quotes, not a passed coverage check.
