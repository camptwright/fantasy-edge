# Experimental NCAAF moneyline deployment

Authorized explicitly by the user on September 5, 2026, overriding validation
gates with the baseline retained. This is NOT an evidence-approved promotion.

Pinned candidate: `ncaaf-moneyline-sigmoid-20260905-v1`, slope 2.0, intercept
-0.25. Applied once to the HOME win probability; the away probability is its
complement. It feeds the existing EV/Kelly calculations and downstream signal
consumers. No bet execution is added. No other sport/market is recalibrated.

The candidate was selected in the evaluation dated 2026-09-05T14:01:33.371555Z.
Historical holdout: 206 games, Brier 0.215988 baseline / 0.202843 candidate,
log loss 0.622198 baseline / 0.590131 candidate. Prospective validation and
independent provenance/uncertainty review remain incomplete. News is still not
a numeric feature. Future evaluations cannot replace these pinned parameters.

Elo functions, ratings, and historical replay remain unchanged. NCAAF moneyline
signal rows and immutable captures retain `baseline_model_probability` and
explicit override metadata. The deployment status is readable at
`GET /calibration/deployment`, and the Calibration page displays a warning.
The forecast fingerprint includes calibration code and the enable flag.

## Rollback

Set `NCAAF_MONEYLINE_CALIBRATION_ENABLED=false` in the application's `.env`,
then recreate `api`, `worker`, and `beat` with the existing Compose files.
No retraining, database changes, or image rebuild is required. Verify that
`GET /calibration/deployment` reports `enabled: false`, and that NCAAF moneyline
rows have identical model and baseline probabilities. Remove the override or
set it to true to re-enable this same pinned candidate. Do not alter old archives.

Without actual paired moneyline quotes, this deployment produces no moneyline
signals. It does not synthesize prices or imply missing markets are covered.
