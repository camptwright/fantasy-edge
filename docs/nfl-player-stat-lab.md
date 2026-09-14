# NFL roster player stat lab

First release: Experimental only. Default league matches Fantasy's alphabetical default; league links select the user's owned roster. Exact Sleeper-to-GSIS/ESPN crosswalk or ESPN IDs only, never name matching. Refresh the public ID artifact with `python -m scripts.build_player_lab_ids` when needed.

## Research and plan

Sleeper omits GSIS/ESPN IDs for many newer players. The [nflverse-documented DynastyProcess crosswalk](https://nflreadr.nflverse.com/reference/load_ff_playerids.html) fills these by exact Sleeper ID. Conflicting mappings are excluded, never resolved by names.

- [nflverse player-stat dictionary](https://nflreadr.nflverse.com/articles/dictionary_player_stats.html): retain stable IDs and game-level observations.
- [Forecasting Principles and Practice](https://otexts.com/fpp3/): use temporal evaluation rather than random train/test splitting.
- [Forecasting with regression](https://www.otexts.com/fpp3/forecasting-regression.html): unknown future covariates must not be treated as observed. Opponent and roster injury labels are context only, not modeled adjustments.
- [Prediction intervals](https://otexts.robjhyndman.com/fpp3/prediction-intervals.html): empirical historical ranges are not calibrated predictive intervals.

Implementation: owned roster → exact identity → final non-preseason NFL history excluding pending corrections → per-stat minimum eight observations → last-20 baseline and conservative last-five-opportunity candidate → chronological last-12 retrospective tests → separate Experimental UI. Missing statistics remain missing, not zero. Candidate is a 50% blend of baseline and recent usage times historical efficiency, bounded within one historical standard deviation of baseline. This recipe is provisional, not optimized or promoted.

## Limits and next validation

QB/RB/WR/TE only. Full-game conditional-on-playing estimates, not live-game updates or availability forecasts. Current data corrections are used in retrospective evaluation, so this is not a point-in-time historical replay. Injuries, opponent strength, depth chart changes and season transitions are not adjusted. Sparse rookies, kickers and defenses remain explicitly unsupported. Roster and last-result timestamps identify freshness; history spans the current and prior two calendar seasons. There is no claim that this candidate beats the production model or the market.

Prospective capture is now a separate 15-minute Celery job (`fantasy.player_lab_prospective`). It freezes the first eligible forecast 5 minutes–72 hours before known kickoff, requires a roster sync within six hours, and deduplicates across leagues. Atomic create-only archives under `nfl-player-prospective/forecasts` retain the baseline, candidate, history summary, injury label, capture/kickoff timestamps, and source-code version hash. Unknown kickoffs are intentionally excluded. Original forecasts never change.

Each run also regrades all captured forecasts against current final stat rows, excluding pending player-game corrections and missing results. Immutable grading reports preserve earlier evaluations while the latest report reflects corrections or retractions. MAE is separated by stat and model version; historical range coverage is descriptive, not a calibrated interval claim. The Experimental page shows capture/grade counts and prospective MAE. No automatic promotion or production model changes.

Next: accumulate actual final results, assess opportunity errors and range coverage by position/season, then evaluate richer role/opponent adjustments against this frozen recipe before any serving promotion. Missing results (including unresolved participation) require investigation, never automatic zero filling.
