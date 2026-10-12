# ESPN final snapshot repair

Root cause: historical ESPN collection updated `scored_history` but not the `matchups` compatibility snapshot consumed by legacy weekly and provider-weekly graders. Three week-two weekly captures remained blocked despite available final history.

Repair: refresh both snapshots from the same explicitly requested historical scoring period, under existing season/rule/final-game checks. Compatibility points are restricted to finite, non-conflicting, season-bound actual totals. Previously observed starters are preserved, not reconstructed from current rosters. Fresh scored history no longer suppresses fetching when the compatibility snapshot is stale. The 24-hour finality delay remains intact.

Validation: 16 focused history/validation tests passed. Production backend images built and deployed. Two consecutive ESPN sync task invocations succeeded. Regrading at 2026-09-29T22:06:46Z changed weekly snapshot waits from 25 to 22 and weekly graded captures from 4 to 7. Provider graded totals increased from 658 to 671; missing final snapshot counts fell from 76 to 57, with six of those now correctly classified as missing/conflicting player points.

The remaining 22 snapshot waits are week-three captures whose latest kickoff was September 29 00:15 UTC; the 24-hour threshold had not passed at verification. No timestamps were backdated and no captured forecasts were overwritten. The source-bound recipe hash changes because score-history ingestion is part of its contract; old-version metrics remain separate. New current-version pregame captures were made, not pooled into prior-version evidence. Three lineup experiments now exist, with no graded simulation metrics yet.

Remaining: verify routine collection after week-three finality delay; investigate missing/conflicting player points separately. This repair does not qualify calibrated lineup probabilities or justify model promotion.
