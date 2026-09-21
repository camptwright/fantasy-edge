# Fantasy decision candidates

The `/fantasy/models` page and authenticated `decision-models` endpoint add
read-only candidates alongside the existing fantasy flows; they do not replace
serving recommendations or submit transactions.

## Weekly matchup and waivers

Provider weekly scoring components are distinct from the historical model.
ADP-only rows are not projections; absent projections are unknown, not zero.
Matchup margin requires both complete starter projections, matching snapshot
weeks, inputs fresh within six hours, known game bindings and a not-started week.
No win probability or remaining-points forecast is asserted.

Waivers use maximum-weight bipartite assignment across the actual roster slots,
including overlapping flex and superflex eligibility. Each add/drop preserves
roster size and is ranked by optimized lineup gain. Current starters and locked
players cannot be dropped. Candidates are bounded to the top sixty unowned
provider-projected players; missing projections limit this search. This first
version does not price FAAB or enforce all platform transaction rules, and is
withheld after the slate starts rather than suggesting illegal lineup changes.

## ROS research

Exact platform identities resolve corrected final player-game history. At least
eight complete observations are required; the most recent twenty are retained.
Historical stat means and the workload-shrinkage candidate are scored under the
league's offensive weights. Unsupported categories (including two-point and
fumble coverage when absent) are explicitly omitted from a labeled subtotal,
never silently interpreted as zero. Kickers and defenses are unsupported.

Daily ESPN season ingestion validates 272 distinct fixtures, 32 teams, 17 games
per team, and no duplicate team/week. This follows the [published 2026 NFL
schedule](https://operations.nfl.com/media/rb2jvpol/05-14-26-2026-nfl-schedule-by-division.pdf).
All 18 weeks are requested independently. `timeValid=false` remains a null
kickoff, not a midnight fixture. Bye weeks are derived only after complete
membership validation. Full ROS is available only with complete scoring and
schedule membership; otherwise its value remains null.
These constant-role, conditional-on-playing sums have no injury recovery,
opponent strength, dynasty, replacement-cost or roster-fit adjustment. Trade
comparisons therefore return no fairness verdict. The older trade proxy remains
separate and unchanged.

## Scoring refresh and validation

The maintained [nflverse stats_player release](https://github.com/nflverse/nflverse-data/releases/tag/stats_player)
provides explicit player-game stats, total fumbles lost, two-point conversions,
fumble-recovery TDs and special-teams TDs. Special-teams forced fumbles and
opponent-fumble recoveries use exact play-by-play role IDs, terminal game markers,
matching final scores and a check against the player's whole-game totals.
Ambiguous sequences remain unsupported; no missing-field zeros are synthesized.
Exact GSIS IDs and season/week/team-pair game matches are required.

The current season refreshes every six hours. Archived observations include
source hashes. Existing facts use two observations at least thirty minutes apart
before corrections apply. The 2025 supplement is backfilled for model history.
Sleeper metadata now refreshes every four hours. ESPN's exact scoring rules and
position overrides are retained separately; unknown rules block full scoring.
ESPN equal-weight return-TD categories are grouped only when all constituents
match. Its kicking-distance buckets, defensive conversion returns and try
safeties are represented explicitly; ambiguous rare plays block evidence.
Official per-player applied totals are retained for weekly grading. Matchups
use their unique match ID, not the shared week number.

## Prospective validation

Every fifteen minutes, immutable archives capture eligible player-game forecasts
five minutes to seventy-two hours before kickoff. Player, league rules, scoring
weights, baseline, candidate and model version are frozen. Full-score ROS
candidates also freeze their remaining schedule at their first eligible origin.
Weekly matchup and waiver decisions are captured only before the week's first
kickoff. No historical run is relabeled as prospective.

Player-game and ROS grades follow current corrected final stats and block on
missing outcomes or pending corrections. Different league/scoring cohorts are
not pooled. Weekly decisions use frozen lineups and current platform player
points after the slate is final; unavailable platform points remain ungraded.
The weekly grader does not reoptimize with hindsight or mistake unclaimed waiver
moves for real transactions. Tests cover missing evidence, duplicate capture,
timing guards, correction regrading, and negative realized waiver gains.

These are research candidates, not empirically promoted models. Actual future
outcomes must accumulate before accuracy can be certified. Kicker/defense ROS,
calibrated matchup probabilities and roster-fit/replacement trade values remain
separate modeling work, not silently approximated by offensive-player scores.

## Live verification, September 14, 2026

### First-model limitations retained before moving to the betting ledger

- Complete scoring coverage is not demonstrated predictive accuracy. These
  candidates remain research-only until genuinely prospective results accumulate.
- Eight complete games are required, with at most twenty used. Rookies, changing
  roles and unresolved identities can abstain; missing history is not zero.
- ROS assumes a constant role and participation in every remaining game. It does
  not estimate injury recovery, opponent effects, dynasty or roster-fit value.
- Kicker/defense ROS and calibrated matchup win probabilities are unsupported.
- Weekly forecasts abstain after the slate begins or inputs become stale; this
  is not a live remaining-points model. Free-agent realized points may be missing.
- Waivers search only sixty projected free agents; FAAB and all platform-specific
  transaction rules are not modeled. No real transactions are submitted.
- Schedule completeness does not resolve the 24 TBD kickoff times below.
- Archived counts below are a dated snapshot, not a claim that those forecasts
  have since been graded or validated. Betting serving models are unchanged.

- Complete 272-game schedule, with 24 legitimately undecided kickoffs.
- Full-scoring offensive candidates: 183 (2016 Warriors), 228 (Inaugural
  Crossover League), 194 (SLO Dev Fantasy League). These overlap across leagues.
- No partial-scoring rows remain among model-ready offensive players; insufficient
  history, unresolved IDs and unsupported positions are still explicit.
- 125 player-game and 99 ROS archives across code versions, all awaiting finals.
  Zero weekly archives because this week had already started; no backdating.
- Repeated current-season ingestion and prospective capture wrote no duplicates.
- 46 focused tests passed; all three live league APIs and auth checks passed.
