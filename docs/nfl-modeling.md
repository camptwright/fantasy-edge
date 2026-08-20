# NFL modeling foundation

Fantasy Edge uses [nflreadpy](https://github.com/nflverse/nflreadpy), the
maintained Python port of nflverse/nflreadr, for offline NFL data. It loads
Polars frames and keeps the dependency out of the API/worker image by placing
it in the `historical` optional dependency group.

Install the batch dependencies and seed completed games with:

```bash
pip install -e '.[historical]'
python -m scripts.seed_historical --sport nfl --seasons 2022 2023 2024
python -m scripts.train_models --sport nfl --seasons 2022 2023 2024
```

The team and player predictor foundation lives in
`src/services/nfl_predictors.py`. `build_team_profiles` and
`build_player_profiles` accept records returned by `nfl_loader`, while
`predict_matchup` and `predict_player_stat` produce explicit `qualified` flags.
No missing value is filled with a fabricated league average. A profile needs
four completed games by default; eight or more games raises confidence to
`high`. These are transparent baseline predictors, not a claim of calibrated
probability. Public assessments must still pass the existing out-of-fold
calibration gate in `src/services/model_health.py`.

The supported nflreadpy sources are schedules, team stats, player game stats,
and player identities. Use its filesystem cache in production batch jobs to
avoid repeatedly downloading the same season:

```bash
export NFLREADPY_CACHE=filesystem
export NFLREADPY_CACHE_DIR=/mnt/data/fantasy-edge/nflverse-cache
```

The first release intentionally does not scrape sportsbooks for player props.
The Odds API remains limited to the configured game markets, and player lines
continue to come from the permitted provider path. A later integration can
join `NFLPlayerProfile` to those lines by the existing normalized player ID and
feed the projection into `MarketAssessment` only after walk-forward evaluation.

## NFL prediction board

`GET /api/v1/nfl-predictions` and the dashboard's **NFL predictions** page use
ESPN's scoreboard competition odds as a secondary source for game spread and
total markets. ESPN rows retain their event id and observation time. A model
probability is attached only when the market type and team selection match a
calibrated persisted assessment; a moneyline probability is never reused for a
spread or total.

Player rows are deliberately shown as `uncalibrated` until the offline
`nflreadpy` artifact has a complete player/game join and passes walk-forward
evaluation. This is a visible coverage state, not an implied recommendation.
