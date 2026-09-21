# Player values and roster impact — September 17, 2026

## Research and design

- [FantasyCalc FAQ](https://fantasycalc.com/frequently-asked-questions): observed
  trade prices are distinct from projected points; format, recency and roster-slot
  costs matter. We did not import their values, copy their fitted algorithm, or
  assume permission for bulk API reuse. A permitted market feed is separate work.
- [RotoTrade](https://www.rototrade.com/): league context, searchable player values
  and understandable trade explanations informed the interaction design. Its
  proprietary forecasts, rankings and championship odds were not copied.
- [Draft Sharks calculator](https://www.draftsharks.com/trade-calculator) and
  [ROS rankings](https://www.draftsharks.com/ros-rankings): distinguish scoring-
  dependent production from broader value and surface uncertainty. Its premium
  projections were not ingested or reverse engineered.

## Delivered

`/fantasy/values` expands beyond rostered players and sixty waiver candidates to
the connected platform's team-assigned fantasy catalog (explicitly inactive
unowned entries excluded). Ownership, exact identity, source freshness, injury
flags, latest result, and current-season history remain explicit. Missing values
are null, never zero. Kicker/defense/rookie estimates are not invented.

Values reuse the existing league-scored, eight-game-minimum workload-shrinkage
research candidate and known ROS schedule. They are not new market prices or a
promoted predictive model. Same-position replacement comparison uses the highest
modeled unowned player with current-season history and no reported injury.
It is an optimistic available-pool benchmark, not a guarantee of waiver access.

Authenticated APIs:
- GET `/api/v1/fantasy/leagues/{id}/player-values`
- POST `/api/v1/fantasy/leagues/{id}/trade/roster-impact`

The trade model reoptimizes both actual rosters with exact offensive starting
slots, including overlapping flex/superflex. Each side gives its selected players.
Unknown values, stale inputs, availability flags, unsupported slots, duplicate
players, cross-roster packages and uneven deals block recommendations. Uneven
trades require an explicit future add/drop plan; none is silently fabricated.
Gains are conditional points per game, not bye-adjusted ROS gains or fairness.
Kicker/defense slots are excluded and clearly labeled as offensive-only impact.

Suggestions search one-for-one swaps among at most eight modeled players on each
roster and require both teams to gain. No trades/claims/lineup changes are sent.
The legacy proxy calculator stays separate and now links to this safer research
view. Production betting models are unchanged.

## Correction-loop repair

Week 1 target counts for two players oscillated between ESPN and nflverse.
The fantasy supplement now preserves an exact current value backed by the latest
applied ESPN correction, archiving disagreements instead of reversing it.
Supplemental-only fields still use normal correction confirmation; ESPN can still
correct its own facts. This is documented source precedence, not proof that two
providers agree. Live current-season refresh preserved two disagreements and
created no new pending corrections. One supplemental source row remains unmapped.

## Validation and remaining work

47 focused offline tests passed; TypeScript and production images built. All
three live league endpoints returned 200 with fresh snapshots in 2.6–3.6 seconds
before inactive-catalog filtering. The page was opened and inspected in-browser.
No mutual trade recommendation qualified under current coverage/availability.

Next: licensed/permitted market-price observations, stable market identity joins,
explicit uneven-package add/drop scenarios, current-role/participation models,
rookie/K/DST models, injury recovery, bye/playoff-weighted roster optimization,
and prospective validation before any promotion. A historical average for a
backup is not proof of a current starting role.

Still gated from prior work: verified venue/roof and college coordinates, fresh
period quotes, exact settlement contracts, historical MLB quote association audit,
and prospective weather/scorer evaluation. These were not falsely marked clear.

## September 20 implementation and live verification

- Deployed daily-cached FantasyCalc documented API ingestion, with attribution,
  exact platform-ID matching, format checks, and 48-hour serving expiration.
  Captured 198 redraft and 419 dynasty observations; a second task run used the
  daily cache. The keeper league remains unsupported. Values are exposed only
  for selected trade players, not as replicated rankings or model points.
- Uneven trades accept explicit free-agent additions and owned-player drops.
  Both roster sizes must balance; invalid ownership and duplicate plans abstain.
  This remains conditional offensive lineup impact, not guaranteed waiver access.
- Provider current-week evidence now supports players without historical-model
  eligibility, including rookies, K and DEF. Missing ESPN totals no longer become
  invented zeroes. Captured 53 pregame forecasts (including six K and three DEF),
  all awaiting final results. These are separate from own-model ROS valuations.
- Football weather bindings reject mismatched provider kickoff times. Rule
  contracts require period definition/completion clauses and source observation
  before quote capture. Three reference pages were archived with hashes, but
  none is a verified settlement contract; no weather/scorer model was promoted.
- Verification: 53 focused tests, TypeScript check, production images, daily-cache
  second run, and live authenticated values/trade endpoint checks. Local preview
  replacement retained a stopped rollback container.

Remaining: independent rookie/K/DST ROS models, supported keeper market format,
actual prospective outcomes, verified roof/coordinates, and exact quote-product,
jurisdiction and effective settlement clauses. Across older historical-model
forecast versions, 567 records still lack complete scoring results; these are
not silently graded or counted as validation successes.

## Follow-up: evidence-backed grading recovery

The next current-season supplement refresh inserted 13,774 facts across 24 final
games, with zero pending/applied corrections and two preserved ESPN disagreements.
Regrading reduced missing-scoring forecast records from 567 to 91 and increased
graded records from 203 to 679. These are records across versions/leagues, not
679 independent observations. The remaining 91 records represent 20 distinct
player-games across seven games. A targeted official ESPN refresh of those seven
games added no facts; no missing stat was converted to zero or DNP.

The shared missing-result queue now includes every frozen fantasy scoring weight,
deduplicated by player/game/stat across model versions and leagues. Supplemental
ingestion now archives unresolved source IDs and separates missing final-game
bindings from missing GSIS identities and conflicting game IDs. No duplicate
non-null NFL GSIS IDs were found in the live database. The player-values market
coverage label was also corrected to describe selected-trade-only coverage.

58 focused tests passed. Remaining gates above still apply: this recovery does
not establish keeper-market equivalence, independent rookie/K/DST ROS accuracy,
or a verified weather/settlement contract. The first provider-weekly cohort is
still awaiting final outcomes.
