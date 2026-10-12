# Multiweek retention research pipeline

Implemented an executable adapter/capture/evaluation path, not a serving replacement.

Run `PYTHONPATH=. python -m scripts.evaluate_fantasy_retention` in the configured worker environment. It uses a fresh NullPool session, read-only repeatable-read transaction, already-collected snapshots and the raw archive. It does not call a projection provider, execute a transaction, promote a model, or change fantasy selections.

For integration into the existing prospective run (already builds each league), call `await run_league(db, lab, league, root / 'retention')` from `src.services.retention_pipeline` after the lab is built. The default horizon is three consecutive NFL weeks, capped at Week 18. A scheduler can alternatively call the standalone `execute()`.

## Contracts

- Future-week projections must actually exist, be observed no later than capture, and be at most six hours old. They are never copied forward from the current week.
- Provider player IDs are scoped to the exact league; team abbreviations must resolve uniquely, and each projected week must have one scheduled, timed game more than five minutes away. Byes require the existing validated 272-game schedule.
- Sleeper component projections require every nonzero league scoring key explicitly present and finite. Omitted categories are unknown, not zero. ESPN uses its league-applied total. This intentionally may withhold sparse feeds rather than assert full scoring coverage.
- At most 15 already-proposed waiver scenarios are compared, with the full original roster, fixed lineup slots, verified byes, and actual distinct weekly forecasts. Incomplete roster membership, unfillable lineups, or missing future evidence withhold the scenario.
- Immutable identity includes season, league, original roster, add/drop, exact weeks, scoring contract, parent model version and retention source hash. The first observation wins for that scenario; reruns cannot replace it with hindsight.
- Evaluation uses the saved before/after lineups, not hindsight-optimal lineups. Every selected player needs a rule-bound `scored_history` value for the exact event and season/week, collected after final kickoff +24h. Missing players or mismatched rules/events withhold the entire result.

This evaluates conditional lineup coverage only. It does **not** price keeper rights, next-season value, injury recovery, unknown future roster changes, or free-agent acquisition cost. Reports stay `serving_promoted: false`; current reports expose requested weeks, fresh available projection weeks and blocking reasons. A three-week horizon with only two available weeks must remain withheld.

## Research basis

[Sleeper's official API documentation](https://docs.sleeper.com/) documents read-only leagues, rosters, matchups, players and drafts, but does not establish a guaranteed full-season projection contract. Accordingly the implementation consumes existing archived projections rather than assuming unsupported future-week endpoints provide usable full-season evidence. Provider totals remain distinct from an independently validated prediction model.

Offline tests cover immutable identity, real week-specific inputs, missing-week refusal, omitted-stat refusal, zero values, stale/future observations, started games, missing/ambiguous schedule binding, incomplete rosters and exact-rule/event frozen grading.
