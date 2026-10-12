# Fantasy completion sweep

## Implementation and acceptance checklist

- Replace input-order waiver tie selection with deterministic ordering and preserve
  every equally good positive-gain drop alternative. Keep starter/lock protection.
- Expose alternative drops in the workspace contract and UI with roster/lock
  revalidation. Weekly ties are not equally good long-term decisions.
- Retain per-move retention warnings; never qualify a drop from conditional ROS.
- Run regression, response-contract, frontend and build checks; deploy matching
  background producers and readers when the recipe changes; verify localhost.
- Recheck specialist/missing-result/prospective evidence using existing archives
  and scheduled jobs, without inventing outcomes or reusing future evidence.

## External evidence and user-input requirements

Update: the owner supplied the one-keeper/no-consecutive-years/no-first-round
rules and round-minus-one cost. The league-scoped evaluator and authenticated
read-only calculation endpoint are implemented, with strict input validation.
65 keeper/workspace tests passed. Draft/previous-keeper evidence must still be
bound before automatic eligibility, and pick-surplus valuation is not implemented.
Undrafted/traded-player/unavailable-pick exceptions remain unresolved.

Keeper pricing requires actual cost units, annual escalation, retention limits
and eligibility. Requested from owner; not inferable from max_keepers=1.
Rookie/DST full ROS qualification requires reconciled categories and independent
holdouts; the kicker recency candidate lost its existing holdout. Current-version
prospective qualification requires actual future games, not retrospective recapture.
The 112 missing player-games were absent by exact athlete ID from archived ESPN
boxscores; absence is not zero or DNP. These remain open until evidence exists.

Engineering completion and model qualification are separate. No deadline changes
the validation standard, and this checklist is not a claim that fantasy is done.

## Implemented and verified this sweep

Waiver tie selection is now stable by player ID and exposes all equally good
rounded weekly drop alternatives. Workspace DTOs revalidate membership, starter
protection and locks before displaying them; the UI links each alternative to
player comparison and does not rank them by retention value.

89 distinct targeted backend tests passed (88 in the initial run plus the
database-backed test on the dedicated test database; the 12-test identity suite
was rerun successfully). All 35 frontend tests passed; the amended render tests
were rerun, and TypeScript, lint and Docker production build passed.
API, worker, evaluation, preview API and preview dashboard were deployed together.
The new cohort is `2365769690592da5244acc2abcee12402e1f100a856ae19b748b8e33746d4a18`.
Existing forecasts were not relabeled into that cohort.

Live browser check: Inaugural Crossover League waiver screen showed a 0.2-point
Jets scenario with ten additional equal-gain drop alternatives and explicit
unresolved retention warnings. A fresh Week 5 roster checkpoint loaded normally.
The latest saved prospective report checked predates deployment: 4,599 graded,
591 awaiting final, 684 missing captures / 112 unique player-games; no capture
blocks. Those counts do not qualify the new model version.

Not completed: long-term retention model and validation, independently qualified
rookie/K/DST ROS, missing participation evidence, keeper rule contract and
current-version prospective outcomes. This is a tested incremental completion
of waiver ambiguity handling, not completion of the entire fantasy phase.
