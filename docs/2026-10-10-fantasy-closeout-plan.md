# Fantasy closeout implementation plan

## Scope and acceptance

1. Complete bounded future-week collection and multiweek retention capture. Preserve missingness, evaluate saved lineups rather than hindsight-optimal lineups, and show the actual available horizon.
2. Freeze specialist candidate and retained-baseline predictions before kickoff; grade exact league-scored finals with version-bound evidence. Unknown kickoff times must not become invented dates or eligibility clearance.
3. Make keeper evidence requirements explicit and fix scenario arithmetic/UI edge cases. Preserve nullable historical flags and unresolved commissioner rules.
4. Expose research status and coverage blockers in the fantasy workspace without launching model work on page requests. Use bounded background summaries.
5. Review recovery/correction handling, run full offline/dedicated-test-database regression, deploy matching readers/producers, and verify multi-league localhost workflows and source fingerprints.

## Research basis

- [Sleeper API](https://docs.sleeper.com/): draft picks can contain null keeper flags; collection must preserve unknown values. Cache bulk player catalogs rather than fetching on navigation.
- [Forecasting: Principles and Practice, time-series cross-validation](https://otexts.com/fpp3/tscv.html): rolling-origin evaluation must match the intended prediction horizon; per-week accuracy is not proof of multiweek/ROS skill.
- [Sleeper keeper costs](https://support.sleeper.com/en/articles/2219811-how-do-i-set-the-round-cost-for-keepers): league commissioner rules determine costs; unspecified trade/undrafted/pick-availability cases require actual rules.

## Non-negotiable boundaries

Engineering completion does not manufacture future observations. Newly frozen
forecasts remain awaiting outcomes until games finish. No automatic promotion,
inferred zero/DNP, fabricated keeper history, platform roster transaction, or
wager submission is authorized by this completion sweep. Unspecified league
rules and provider coverage failures are reported explicitly rather than hidden.
