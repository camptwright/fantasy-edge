# NCAAF prop coverage expansion

Added six research/outcome families: pass_rush_yards, rush_rec_yards,
rush_rec_tds, fg_made, xp_made, and kicking_points. ESPN kicking keys were
verified against the live completed-game summary. Made/attempt pairs must be
finite nonnegative integers with made <= attempts; DNP and malformed rows are
not recorded. Composite facts require both recorded components; missing is
never filled with zero. A sum is exact but its observed-only history can be
selection-biased and is not automatically a calibrated distribution.

`fantasy.expand_ncaaf_props` runs hourly, derives complete-component history,
then revisits up to 50 existing finals with versioned `ncaaf_prop2_` audit keys.
It adds facts without overwriting existing stats or touching Elo ratings. Both
this job and current-week result ingestion share a Redis lock. Missing kicking
blocks or non-final/mismatched responses get deferred without a success marker.
Player identities still use the established crosswalk; unresolved players can
remain missing in otherwise processed games. Provider corrections require
separate review rather than overwriting facts automatically.

After each backfill batch, research refits/re-evaluates all 19 supported primitive
and composite families using prior-day features and a chronological holdout.
V2 reserves roughly the latest 30% of samples, keeping the boundary UTC date
entirely in the holdout; the split uses counts/timestamps, never outcomes. This
avoids a tiny bowl-heavy holdout from counting dates instead of samples. The
original deployed v1 artifacts and their reported evidence remain unchanged.
Its report is atomically archived under raw/prop-research. Insufficient
holdouts now include sample/game counts and the minimum requirements. These
reports do not automatically replace the pinned deployment. After manual review,
v2 adds passing_yards, pass_rush_yards, rushing_attempts, rushing_touchdowns and
receiving_touchdowns under the user's experimental override. Existing spread
and receptions coefficients are retained exactly; moneyline is untouched. The
new fits have 103–141 independent holdout games and improved both historical
distribution loss and point RMSE. These are not prospective or bookmaker-quote
validation results. The same NCAAF_PROP_CALIBRATION_ENABLED=false rollback flag
disables every prop override. The pinned artifact is versioned v2; prior v1
forecast archives retain their original evidence and probabilities.

Follow-up v3 adds the three kicking families after expanding their recorded
history. It uses mean-preserving uncertainty calibration and retains every v2
market coefficient. See `docs/ncaaf-kicking-override.md` for the current deployment
evidence, limitations and rollback; the v2 account above is deployment history.

`GET /calibration/prop-readiness` and the expandable NCAAF prop coverage section
on the Calibration page expose quote qualification, outcome counts, research
state and reasons. Latest-per-player/stat/source quote counts are not distinct
games, bets, or guaranteed pregame offers. Active override means enabled—not
prospectively validated. Candidate review means only the historical distribution
screen passed; it is not an approval to use the candidate.

Specialty props such as fantasy_points, first_td_scorer, game_high_* and period
markets still require explicit scoring rules, broader participation coverage,
play-by-play or joint-event modeling. They are not assigned fabricated models.
