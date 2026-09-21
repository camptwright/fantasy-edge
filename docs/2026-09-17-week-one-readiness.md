# September 17: NFL Week 1 and context coverage

## Verified against the running app

- All 16 regular-season Week 1 games are final with player statistics: 1,118
  distinct players and 34,216 stored stat rows. Row counts include participation
  zeros and multiple categories; they do not represent independently validated
  predictions.
- Re-fetched all 16 official ESPN box scores: no missing players, deferred games,
  or new rows. Two target-count corrections await the normal 30-minute repeat
  observation: Drake London 4 to 5 and Jahan Dotson 3 to 4. Their whole player-game
  histories are excluded pending confirmation, leaving 34,151 eligible Week 1 rows.
- Actual serving passing-yard projections for all 35 qualifying quarterbacks
  match means including Week 1. Two additional quarterbacks have insufficient
  history. This is inclusion proof, not predictive-accuracy validation.
- All 32 NFL team scoring aggregates/counts match the stored final-game history.
- Experimental NFL game predictor reports 16 new results applied beyond its
  frozen training-history cutoff. No coefficients or serving promotions changed.
- Reproducible audit: `src.services.nfl_week_audit.audit`; immutable report under
  `raw/nfl-week-audit/20260917T130229.555127-523bdf64a25f47c285f74664a706037c.json`.

## Repairs deployed

- Fixture fallback now rejects conflicting same-provider game IDs, preventing
  adjacent MLB series games/doubleheaders from collapsing into one event.
  Quote matching prefers the nearest kickoff and rejects equal-distance ties.
- Reconciled 140 MLB schedule entries through the official-ID ingestion path.
  Latest eight-game MLB weather capture had no kickoff mismatches (six forecasts,
  two indoor exclusions). This does not certify older quotes/stat associations;
  historical observations were not rewritten or silently reassigned.
- Period capture supports provider `rec_yards` aliases while reading validated
  `receiving_yards` labels; rushing-attempt labels bind to historical `carries`.
- Exact name/city/postal football venue matching can archive secondary survey
  coordinates, with source-row evidence and dataset SHA256. It never establishes
  roof state or turns on numerical weather adjustments.

## Evidence-bound gaps, still not cleared

- Latest period capture has no eligible fresh upcoming quotes. Inspected receiving
  and passing period quotes belong to completed games and were last seen September
  7. Do not bypass freshness/pregame checks or call these live opportunities.
- Latest context capture: seven forecasts, two indoor exclusions, eight college
  venues without coordinates and seven fixtures with unknown kickoff. The NFL
  coordinate match is secondary evidence with roof still unknown.
- Missing official roof/college coordinate evidence, exact settlement contracts,
  and prospective paired evaluation still prevent weather/scorer promotion.
- Corrected MLB identities do not retroactively validate historical quote links.
  A historical source-event reconciliation is needed before using those affected
  observations as new validation evidence.

Validation: 20 focused offline tests passed (fixture collision/tie handling,
weather binding, context evidence, period aliases and research safeguards).
