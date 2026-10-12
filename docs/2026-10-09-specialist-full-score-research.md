# Specialist full-score candidate evaluation

The new `specialist_full_score_shrinkage_v1` model shrinks up to eight own
observed weekly totals toward the prior position cohort mean (four pseudo-games).
Two prior personal observations are required; this is a research comparison,
not a relaxed serving-history threshold. Forecast all players in a week before
adding that week's outcomes. Scoring contracts and leagues cannot be pooled;
missing totals are never zero. Current-season corrected provider results are
retrospective evidence, not prospective availability evidence.

Read-only evaluation completed October 9, 2026 using existing `scored_history`
archives and provider position metadata. Baseline is own-history mean, not the
existing provider projection; these results do not show superiority to provider.

| League | Cohort | n | Baseline MAE | Candidate MAE |
| --- | --- | ---: | ---: | ---: |
| ESPN | K | 30 | 4.8444 | 4.0788 |
| ESPN | DST | 26 | 5.4615 | 4.2400 |
| Dynasty | K | 22 | 4.3939 | 3.7428 |
| Dynasty | DST | 22 | 5.3182 | 4.7048 |
| Keeper | K | 21 | 4.7619 | 3.9795 |
| Keeper | DST | 13 | 5.2308 | 4.7147 |

All improvements require prospective confirmation and are small, overlapping
samples of observed rostered players, not independent season trials. No model
was promoted. No current/future outcomes entered their own forecasts.

`src.services.fantasy_specialist_totals.forecast` exposes a research per-week
forecast; `holdout` evaluates K/DST and explicitly verified rookie cohorts.
`scripts.evaluate_fantasy_specialist_totals` evaluates current archives without
writing data. Rookies are not inferred from incomplete personal game histories
or current experience fields: season-specific verified cohort evidence is still
needed. Full ROS also needs validated future participation and per-week coverage;
the per-week estimate is never multiplied by games remaining as a ROS forecast.

The retention pipeline's exact future-week adapter is the appropriate input for
multiweek provider forecasts. Its incomplete horizons must remain incomplete.
Existing serving projections are unchanged by this experiment.

Research references: [Sleeper scoring options](https://support.sleeper.com/en/articles/3998131-what-scoring-options-are-available)
describe league-custom scoring categories, while [nflverse data loaders](https://github.com/nflverse/nflreadr/blob/main/R/data.R)
separate player statistics, team statistics, rosters, participation and draft
records. These support keeping score totals, cohort identity and participation
as separate evidence contracts, rather than treating one as proof of another.
