# Frozen MLB count-only prospective experiment

Recipe: `mlb_count_only_v1`. Primary market: MLB RBIs. Hits, runs, home runs,
and pitcher strikeouts are exploratory families, not interchangeable primary
tests. The September 8 retrospective analysis is hypothesis-generating only;
none of those reconstructed forecasts is inserted into this prospective cohort.

Frozen formula: use the archived historical mean unchanged; target variance is
half the archived historical variance plus half the historical mean. Use the
existing bounded Poisson/negative-binomial count distribution. At least four
historical games are required. There is no recency, opportunity, injury, or
opponent mean adjustment. Integer lines retain push mass and score OVER
conditional on a non-push. Invalid or unsupported cases emit no candidate.

The candidate is added only to newly captured, eligible MLB forecasts, on the
existing 15-minute schedule. It cannot price a recommendation. A separate recipe
fingerprint includes its implementation, distribution helpers, and feature
construction. Existing serving/cohort fingerprints and legacy shadow versions
are unchanged by adding this experiment.

Grading uses the saved retained baseline probability, never substitutes the
served override when that baseline is missing, and uses the existing prospective
window and review gates. The window starts on the first capture's UTC day and
runs 30 days plus seven days for grading. Missing outcomes, inadequate independent
games, uncertainty, and benchmark checks continue to block promotion. No automatic
deployment or retrospective promotion is authorized.

Every shadow recipe has its own earliest captured prediction per serving cohort,
player, game, and market. A recipe added after an earlier baseline-only capture
is enrolled from its actual first shadow capture, not dropped or backdated.

Inspect `shadow_reports` in the latest grading archive or the existing calibration
grading API for recipe names beginning with `mlb_count_only_v1:`. Per-market
sample counts are distinct; repeated props from one game are correlated.
