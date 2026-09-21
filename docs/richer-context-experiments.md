# Richer weather, news and period/scorer experiments

Started September 15, 2026. Research only; retained serving models are unchanged.
Pending ledger evidence is recorded in `pending-receipt-evidence.md`.

## Implemented foundations

- News evidence now requires full normalized-name boundaries and a 72-hour
  observation window. A parseable publisher date must also fit that window.
  Publisher dates never override the observed-at anti-leakage gate. Missing dates
  remain unknown; headlines do not confirm injury, starting status or game role.
- Open-Meteo adapter requests explicit UTC, Celsius, km/h and mm hourly forecasts.
  Selection validates units, missing data and pre-capture availability, retaining
  temperature, humidity, precipitation probability/amount, wind, gusts and direction.
  Closed roofs exclude outdoor weather; retractable roofs remain exposure-unknown.
  Four hourly forecast windows are NOT relabeled as football quarters.
- Joint scorer evaluation uses a shared frozen player universe with explicit
  OTHER and NO-SCORER outcomes. Baseline/candidate multiclass Brier and log-loss
  deltas are reported separately by market, once per game/market. Training evidence
  must predate capture; capture must predate kickoff; unresolved corrections block
  scoring. No bookmaker settlement, EV or production promotion is inferred.

Weather contract: [Open-Meteo forecast documentation](https://open-meteo.com/en/docs).
Forecast fetch timestamps record our availability, not model issuance timestamps.

## Next implementation stages

### September 16 audit improvements

The hourly job was healthy (30 reports, 39 distinct game archives), but selecting
only the earliest eight fixtures could starve later events. Capture now prioritizes
unobserved games, then the oldest archive, keeping the same eight-per-sport request
budget and a bounded 500-event scan. Reports expose scan coverage and freshness.
MLB provider kickoff changes block venue binding until schedule reconciliation.
New event hashes are reproducible from archived canonical JSON. Malformed weather
units/arrays now return explicit gaps instead of raising while capturing forecasts.
Football coordinate/roof evidence remains unresolved; no numerical promotion.

### September 15 deployment update

Event-level capture is now scheduled hourly, bounded to eight games per sport
within 72 hours (NFL, NCAAF, MLB); unknown kickoff rows remain explicit. Exact
MLB gamePk → event venue → hydrated venue coordinates and roof type is supported.
ESPN football event IDs bind venue IDs/names, but the inspected payloads lack
coordinates, so football weather remains blocked rather than geocoded by team.
Public sources are stored with timestamps in immutable per-game archives.

Live initial run: 17 event records; seven MLB forecast archives, one MLB closed
roof exclusion, two football venue bindings missing coordinates, and seven NFL
unknown kickoffs. NFL/MLB candidate lists exceeded the per-run cap; truncation is
reported. This is bounded coverage, not all-slate completion.

Production forecast capture and football period-shadow capture now freeze prior
weather archive identity, venue evidence, forecast features and explicit gaps.
Archives newer than the snapshot, stale archives and changed kickoffs are excluded.
The recipe is `frozen_context_observation_v1`: covariate collection only, with no
fitted context coefficient or numeric adjustment. Serving probabilities remain
unchanged. The authenticated `/experiments/weather-context` endpoint and
`/experimental/weather` page expose the most recent collection report.

Remaining stages below still require football coordinate/roof evidence, richer
news relevance and paired training/evaluation; weather capture itself is now live.

1. Bind actual event venues and coordinates from verified event evidence, including
   neutral/international sites and roof state. Do not infer venue from home team.
2. Schedule bounded forecast capture and immutable source archives; expose forecast
   age and venue gaps. The adapter is implemented but NOT yet scheduled or connected
   to a live venue registry. No weather coverage claim is made yet.
3. Archive richer news provenance and explicit player/team/game relevance; retain
   contradictory reports separately. Add source-health/freshness labels in the lab.
4. Freeze weather/news context alongside future period/scorer predictions. Evaluate
   context-free and context-aware candidates on identical games and selection
   universes with walk-forward fitting. No guessed weather/role coefficients.
5. Train phase rates on validated history and build prospective joint-scorer outcome
   packets; the new evaluator alone does not mean those packets exist. Exact
   participation, overtime, scorer attribution and rule evidence remain gates.
