# Fantasy recovery sweep — October 8, 2026

## Verified findings and work

The 684 missing-scoring-result forecast captures represent 112 distinct canonical
player-games across 45 final games, not 684 independent missing outcomes. All 112
player-games have zero stored result rows. A bounded refresh of those exact games
through the existing ESPN audited result-repair path completed: 45 games, zero
deferred, zero unmapped players, zero new rows and zero pending/applied corrections.
This does not prove DNP, inactivity or zero points. Another identical fetch is not
an evidence-based remedy. Independent participation/result evidence remains open.

Grading now reports missing-player versus missing-category blockers while keeping
the existing missing_scoring_results status compatible. Saved reports include
deduplicated repair-target counts across versions/leagues. The preview's legacy
fantasy validation screen displays the same distinction with no independent-trial
claim. The report generated at 11:51:18 UTC verified 684 captures / 112 player-games /
45 games / 572 repeated captures, all classified missing_player_results; capture
blocks were empty. Prediction/cohort identities are not changed by this evaluator
diagnostic change. Checkpoint recipe compatibility still requires coordinated code.

The archived kicker candidate evaluation was rerun successfully in an isolated
one-off evaluation container after an initial attempt was interrupted during the
worker deployment. Each league had 459 evaluated games from 38 kickers (84 excluded).
Baseline/candidate MAE: ESPN 3.9292/3.9421, dynasty 3.9345/3.9482, keeper scoring
3.5922/3.6042. Retain baseline in all three. This is retrospective kicking-component
research, not full ROS qualification. Rookie and DST models remain unfinished.

## Acceptance

- 872 backend tests passed, 1 skipped, 20 live tests excluded.
- 35 frontend tests, TypeScript, lint and production build passed.
- Deployed API, worker, evaluation, preview API and preview dashboard. Source
  matched on all four backend services; dashboard source and 171 artifacts matched.
- Browser acceptance remains blocked. Auto-review rejected renewed browser access
  because the prior approval-service block remained in effect. No alternate browser
  surface or shell/browser workaround was used. User approval is needed to retry.
- No synthetic zeros, deleted captures, retroactive forecast edits, model promotion,
  threshold relaxation or fantasy-platform transaction occurred.

## Still not complete

### Follow-up: exact archived athlete evidence

Added `scripts/audit_fantasy_missing_results.py`, a read-only diagnostic that
deduplicates the latest missing-result captures, resolves ESPN athlete IDs, and
checks archived final-event boxscore rows. It does not fetch providers, write to
the database, rewrite captures, or assign zero outcomes. Its three focused tests
pass, including unknown-team handling, wrong-event/identity rejection, and
conflicting DNP/participant rows.

Executed against report `2026-10-08T12:13:42.730276+00:00-eb203468784648f49af42f2fb3d53318.json`:
all 112 targets have a single mapped ESPN athlete ID and a matching final-event
archive, but none of those athlete IDs appears in the archived boxscore rows.
All 112 canonical current-team fields are null: this is unknown metadata, **not**
112 proven team/game mismatches. The earlier mismatch hypothesis is unsupported.
These results narrow the recovery task to independent participation/roster and
athlete crosswalk evidence; re-running the same ESPN result parser cannot recover
rows absent from its payload. Absence does not establish inactivity or zero points.
The script was executed in the existing worker via stdin; no serving deployment
was needed or performed for this diagnostic-only addition.

Independent evidence for the 112 missing player-games; independently evaluated
full-scoring specialist ROS models; current-version prospective outcomes; official
inactive/participation coverage beyond event injury reports; final browser/mobile
acceptance. Keeper-specific pricing also needs an explicit cost/rule contract.
The broad UI redesign remains deferred. This sweep improves diagnostics and checks
recovery/evaluation paths; it does not falsely close these substantive gaps.
