# Independent NFL Predictor Lab

Page: `/nfl-predictor`. Read-only API: `/experiments/nfl-predictor`.
Verified in the user's browser at `http://localhost:13000/nfl-predictor`.
Important deployment detail: localhost port 13000 belongs to the separate
`fantasy-edge-grading-preview` container, not the Compose dashboard service.
Updating only `docker compose ... dashboard` does not update this preview.
The preview now runs the tested dashboard image on `fantasy-edge_fantasy`,
with its original environment and loopback-only 13000:3000 binding preserved.
The previous stopped container is retained as
`fantasy-edge-grading-preview-before-predictor` for rollback (no volumes).
Matchup selection and neutral-venue display were verified in the browser.
Concept references: https://www.axonlearn.app/nfl and
https://www.instagram.com/reel/DdAuAvmhRrU/ . Public educational descriptions
only; no proprietary notebook copied, no affiliation or borrowed accuracy.

## Fixed first recipe

Public nflverse schedules/results, 2015–2025: 3,028 completed games, 2,953
eligible binary training examples after warmup and ties. Preseason excluded;
postseason included. Franchise moves use explicit abbreviation aliases.
Inputs: Elo difference, rolling-eight scoring margin/win share/points
scored/points allowed differences, capped rest difference and home venue.
Elo starts at 1500, K=20, home advantage=65; regresses one-third each offseason.
Rolling history crosses seasons. A standard scaler and logistic regression
(C=1, fixed seed 17) are fitted only to each training fold.

All features are generated before applying the day's results. No same-day
results, closing prices, final-season totals or current ratings leak into
historical pregame examples. Results are current corrected data, not archived
as-published results: retrospective source-revision bias is still possible.
Ties update ratings/history as half a win but are excluded from binary
training/evaluation. Displayed probabilities are conditional on no tie.

## Evaluation

Expanding-season tests: train on seasons before 2022 and test 2022; repeat
through 2025. No within-season model refit, random split or tuning on the test
season. Earlier results in each test season legitimately update team features.
Pooled N=1,136: candidate accuracy 63.73%, Brier 0.22284, log loss 0.63605.
Replayed Elo: 60.39%, 0.22902, 0.64931. This is a separately replayed reference,
not a comparison against saved production forecasts or market odds.
No statistical significance or prospective-profit claim; no promotion.

## Operation and isolation

Build manually with `.venv/bin/python -m scripts.train_nfl_predictor_lab`.
It downloads public nflverse data and writes `config/nfl_predictor_lab.json`.
Artifact carries training cutoff, data hash, coefficients/scaler, state and
evaluation. The API needs no sklearn import or outbound provider request.
It reads upcoming NFL fixtures plus newer finalized results from the app;
same-day finalized results wait until the following Eastern date. Weights
remain frozen while team features update. Earlier historical corrections
require rebuilding the artifact. No scheduler or automatic promotions added.

Nothing modifies production ratings, quotes, prediction snapshots, Kelly,
Best Bets, model approvals or calibration. No Odds API credits used.

## Known limitations

No quarterback/lineup/injury/weather/market features or numerical adjustments.
No exact-score model, no tie probability, no prospective result archive yet.
Neutral venues use the downloaded schedule match (teams and Eastern date);
unknown venues are explicitly labeled as a home-venue assumption. Rest is
capped at 14 days, not a claim that offseason rest is actually 14 days.
Future games use currently available history, not imagined intermediate wins.
Feature rows are descriptive comparisons, not causal attribution.
Next steps: freeze prospective forecasts, grade after results, inspect
season/week-clustered uncertainty, and compare additional features without
reusing these test seasons as a tuning leaderboard.
