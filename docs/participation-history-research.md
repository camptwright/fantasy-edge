# Participation repair and history research

## Serving boundary

These changes repair observed facts, not the mean/stddev probability formulas or calibration overrides.
New verified facts can change ordinary history-based projections. Original forecast
archives and saved retained-baseline probabilities are never rewritten. Candidates
are research-only and cannot auto-promote.

The post-backfill audit exposed legacy spring-training fixtures entering the
normal retry queue. Serving projections, feature snapshots, and prop backtests now
exclude PRE games; serving additionally requires known past kickoff and final
status. Stored facts remain auditable. This eligibility correction legitimately
changes the model/cohort fingerprint and the dependent shadow recipe digest; it
does not rewrite or merge historical forecast cohorts.

## Participation and identity

`src/ingest/participation.py` derives only zero **receptions**, and only when:

- the existing football parser verifies the requested event is final;
- the athlete has a positive, explicit rushing-attempt result in the same team's boxscore;
- there is exactly one receiving block with unambiguous, unique individual rows;
- individual reception counts sum exactly to the team's explicit total;
- that total equals the passing block's explicit completed-pass total;
- the athlete is absent from the receiving block and no category marks them DNP.

No roster-based zeros, targets, receiving yards, longest receptions, voids, or DNP
settlements are inferred. Receivers with no observed rushing appearance remain
unresolved if they are absent from the receiving block. Complete snap/participation
reports are still needed to close that remaining coverage gap.

MLB and NCAAF historical participants are seeded from native boxscore athlete IDs
and names. Existing provider IDs take precedence. No historical name join is used;
NFL remains on the existing GSIS/provider crosswalk. Per-ID advisory locks serialize
concurrent new-player creation. Current team membership is deliberately not inferred
from a historical game. Missing position metadata stays null.

Every repaired observation archives its raw provider payload, payload hash, and
derived reception-zero evidence under `result-observations/`; its path is recorded
in the existing sync ledger. Archive evidence alone is not proof of a committed
observation: the transaction can still roll back after archiving.

## Backfill

```
python -m scripts.repair_history --sport mlb --season 2026 --max-games 3000
python -m scripts.repair_history --sport mlb --season 2026 --max-games 3000 --apply
python -m scripts.repair_history --sport ncaaf --season 2025 --max-games 800 --apply --refresh
```

Dry-run is default. The script discovers final regular/postseason MLB fixtures from
the official season schedule, excludes cancellations and preseason, preserves
doubleheaders by gamePk, and reconciles duplicate suspended/resumed listings only
when identity and final scores agree. New historical fixtures do **not** update
current Elo ratings. Missing team aliases are reported, never guessed.

Results are processed in bounded batches using per-game transactions, existing
row locks, and a 250 ms pause after each game plus a pause between batches. A separate
connection retains the manual-run advisory lock across per-game commits. Normal
scheduled repair pacing remains unchanged. `--refresh` is an explicit one-time
re-observation of selected games, not a permanent retry override; even refreshed
corrections still require two observations at least 30 minutes apart.

Reports live under `history-repair/` and raw schedules under `history-schedules/`.
An interrupted run retains committed game progress; rerun the same bounded command.
The normal workers continue handling deferred or partially mapped results.

For NCAAF, `--discover-football` scans weekly FBS scoreboard windows (including
FCS opponents). Unknown aliases may be resolved from ESPN's native team ID,
display name, and abbreviation in the verified schedule. This occurs in the
central identity module; abbreviation collisions or malformed identities are
reported rather than guessed. Historical team creation initializes no ratings
and does not add a fitted opponent adjustment or new prospective eligibility.

## Frozen research recipes

Run `python -m scripts.evaluate_history_candidates` after the backfills finish.
The output is archived under `history-candidate-evaluation/`.

- `repaired_history_control_v1`: unchanged all-history normal formula using the
  repaired, strictly pre-capture game history; minimum eight outcomes.
- `season_shrinkage_normal_v1`: prior-season mean contributes eight pseudo-games,
  combined with current-season outcomes; requires eight prior-season games and at
  least one current-season outcome. The control's sigma is retained.
- `observed_workload_normal_v1`: outcome/usage rate from up to 20 paired appearances
  times the last five paired appearances' mean usage; 50% blend with control mean,
  capped at one control standard deviation. Requires eight paired appearances.
  Pitcher strikeouts require explicit historical `pitching_games_started`; only
  outings matching the last observed role are paired. This is **not** confirmed
  future starting status. PA, targets, attempts, and outs are never imputed.
  Explicit zero-opportunity appearances remain in the paired sample; only missing
  opportunity fields are omitted, and total exposure must be positive.

Constants were fixed before examining candidate scores. Each recipe is compared
with the saved retained baseline on identical quotes/outcomes. A second comparison
uses the repaired-history control to separate new-data effects from model-formula
effects. Selection is the earliest valid archived capture per player/game/canonical
market, not one sample per bookmaker quote. Results include Brier/log loss and
game-cluster bootstrap intervals; intervals are not multiple-comparison adjusted.

The evaluation is **retrospective**, not prospective validation. History publication
and ingestion timestamps are unavailable, and newly repaired historical data might
not have existed in the app at the original capture. Future/target-game observations,
preseason, disputed pending corrections, pushes and missing outcomes are excluded.
No result from this report qualifies a candidate for promotion by itself.
