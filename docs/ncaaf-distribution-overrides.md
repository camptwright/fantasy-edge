# NCAAF spread and player-prop experimental overrides

User authorized building/testing candidates and deploying under an override,
with baselines retained, September 5, 2026. This is not a validated promotion.

Pinned artifact: `config/ncaaf_experimental_distributions.json`, candidate
`ncaaf-distributions-20260905-v1`. Reproduce the training report with
`python -m src.services.ncaaf_candidate_training` (read-only; does not publish or
replace the pinned file). Inputs are final known-time NCAAF games and canonical
player results; legacy interception aliases do not duplicate canonical history.

Features are frozen for all games on a UTC date and updated after that date.
Players require four previous observed results and positive historical standard
deviation, matching the current serving baseline. The earliest 70% of distinct
feature dates fit the correction; the remaining dates evaluate frozen parameters.
This is a date split, not a 70/30 split by sample count. No holdout outcomes enter
coefficient fitting. The holdout is then used to select which candidates deploy,
so it is not an untouched final validation set after this selection.

## Selected

| Candidate | Fit samples | Holdout samples / games | Baseline RMSE → candidate | Baseline Gaussian NLL → candidate |
| --- | ---: | ---: | --- | --- |
| Spread (home margin) | 603 | 82 / 82 | 19.9102 → 17.5430 points | 4.4380 → 4.2900 |
| Receptions | 1,793 | 170 / 30 | 2.0228 → 2.0186 receptions | 2.8990 → 2.2367 |

Spread learns slope/intercept/sigma around the existing Elo implied margin.
Home cover probability uses threshold `-home_line`; away is its complement.
Receptions learns a pooled residual location/scale correction around each
player's existing mean/stddev. Both feed existing EV calculations, and spread
feeds existing Kelly calculations. Predictions are not placed as bets.

Five passing-stat candidates lacked sufficient held-out history. Seven other
prop candidates failed the joint distribution-loss/RMSE screen and were not
deployed. Unlisted specialty props, totals, other sports and unsupported/unlinked
or non-pregame events retain their existing behavior. Moneyline remains on its
separately authorized override.

## Evidence limitations

These are distribution forecasts evaluated against actual margins/player stats,
not graded historic betting quotes. Gaussian NLL is a density score—not binary
log loss, Brier score, or profit. A normal distribution is only an approximation
for discrete reception counts. No bookmaker-specific push/DNP settlement,
injury/news adjustments, independent market benchmark, or prospective validation
was added. Historic published-at timestamps are unavailable; the prior-day
assumption does not prove point-in-time data provenance. Prop samples within
games are correlated. The 30-game receptions holdout is small.

## Serving, audit, and rollback

Both enable flags default true for this explicitly authorized release. API and
forecast records retain baseline probabilities; prop records also retain baseline
projection and served mean/stddev. The forecast fingerprint includes the pinned
artifact's SHA256 and effective flags. Grading reports paired baseline Brier and
log loss wherever saved baseline probabilities exist. Earlier archives are unchanged.

`GET /calibration/deployment` exposes nested `distributions` evidence and status.
The Calibration dashboard warns that overrides are experimental. A missing or
malformed artifact falls back to baseline. The artifact is loaded once per process;
no scheduled evaluation can automatically overwrite the deployed coefficients.

To roll back, set `NCAAF_SPREAD_CALIBRATION_ENABLED=false` and/or
`NCAAF_PROP_CALIBRATION_ENABLED=false` in the app `.env`, then recreate api,
worker, and beat with the existing Compose files. No rebuild or database mutation
is needed. Verify the corresponding deployment flag/list is disabled/empty and
served probabilities equal retained baselines. This does not change moneyline;
its separate rollback flag is `NCAAF_MONEYLINE_CALIBRATION_ENABLED=false`.
