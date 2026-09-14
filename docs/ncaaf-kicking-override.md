# NCAAF kicking calibration

The kicking families are `fg_made`, `xp_made`, and `kicking_points`.
Historical results come from completed ESPN boxscores using established player
identities. Missing appearances and unavailable fields are never zero-filled.
An accelerated, bounded pass uses the existing `fantasy.expand_ncaaf_props`
task and its shared lock; the hourly incremental schedule remains unchanged.

V3 research keeps kicking means at each player's recorded average and fits only
the standard-deviation multiplier. The fit is the root mean squared standardized
residual, bounded to [0.5, 3]. Mean bias is fixed at zero **before** evaluation;
this is not a search over holdout results. Other research families retain their
existing mean/scale fit. Serving continues to use the existing Normal
approximation, not a new discrete count or bookmaker settlement model.

The existing requirements remain: four variable player-history observations for
a baseline projection; ten replay feature dates, 100 fit observations, 50 held-out
observations and 20 held-out games for candidate evaluation. All observations on
the boundary date stay in the chronological holdout. Historical distribution loss
must improve; point RMSE stays unchanged by design because the mean is retained.
No sample threshold is lowered to force eligibility. Manual approval is tracked
separately from this screen: a requested override can be served with
`user_override_approved=true` while `deployable_experimental=false` accurately
records that it failed the historical screen. Parameter bounds still apply.

## Deployment on 2026-09-05

Candidate `ncaaf-distributions-20260905-v3` adds all three kicking families under
the user's explicit override. The bounded backfill completed 596 additional games,
bringing the completed pass to 696 finals with none remaining at verification.
Each kicking family has 822 recorded observations across 560 games and 128 known
players; missing or unresolved player records remain absent.

The final research snapshot was archived at 23:17:22 UTC. It reserves all dates
from 2025-11-22 onward for evaluation and fits through 2025-11-20. Results:

| Family | Fit rows | Holdout rows / games | Stddev multiplier | Baseline / candidate NLL | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Field goals made | 279 | 140 / 105 | 1.774894 | 1.973535 / 1.712732 | Screen passed |
| Extra points made | 281 | 138 / 105 | 1.652184 | 2.117658 / 2.140563 | Manual override; screen failed |
| Kicking points | 285 | 142 / 106 | 1.905057 | 3.496976 / 3.004956 | Screen passed |

Extra points' final NLL was about 1.1% worse, despite passing in a smaller,
incomplete-history preliminary check. The final failed result is retained; no
earlier favorable snapshot was substituted. The user's requested override is
explicitly recorded, not represented as improved or validated. All means and
point RMSE remain unchanged. Deployment/readiness expose the failed-screen
warning and the underlying pinned evidence. Other v2 market records are retained
exactly, with the previous artifact saved at
`config/archive/ncaaf-distributions-20260905-v2.json`.

Post-deployment verification at 23:21 UTC: 97 regression tests passed (one live
test deselected). Qualification was 18/28 FG quotes, 19/28 kicking-points quotes,
and 14/23 XP quotes; six pregame quotes per family received the override. The
forecast archive captured all 18 with original baseline probabilities and
served parameters intact. Research and grading tasks succeeded, and the live
dashboard rendered the explicit XP failed-screen warning. The two upcoming
quoted kickers still lacking recorded FG history were Gabe Panikowski and Gavin
Lahm; no projection was fabricated for them. Counts are a point-in-time snapshot,
not a claim that every quote is a distinct bet or still available.

Known, scheduled future NCAAF events are the only eligible override scope.
Unlinked, started, unsupported or insufficient-history props do not acquire an
override. Immutable forecasts retain the baseline probability, served parameters,
candidate identifier and artifact digest. Grading treats observed zero as a real
outcome, pushes as excluded and missing stats as ungraded.

These candidates are experimental user overrides, not prospective validation.
Publication times for historical results are unavailable, the distribution
holdout is used for promotion, Normal approximations are imperfect for counts,
and news is not an input to the current numeric model. Future captured forecasts
must establish whether binary probability calibration actually improves.

Rollback: set `NCAAF_PROP_CALIBRATION_ENABLED=false` and recreate api, worker and
beat. This disables all prop overrides while retaining the baseline. Spread and
moneyline switches remain independent. Prior immutable forecast archives retain
their original candidate evidence.
