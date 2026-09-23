# Fantasy distribution coverage: platform-scored history

Live Warriors blockers were Brandon Aubrey, Jake Bates, Baltimore defense
and Green Bay defense. Both kickers had component history but not full
league-scored distributions; defenses had no canonical player history.

Sleeper sync now collects completed prior-week league `players_points`
into `scored_history` snapshots. Collection requires complete season schedule
membership, every game in the week final, and at least 24 hours since every
kickoff. Existing successful weeks refresh daily for provider corrections.
This uses the existing public Sleeper connection, not a paid odds feed.

Snapshots carry season, week, scoring hash, observation time and game IDs.
Only exact platform IDs in the same league and scoring cohort are used.
Conflicting or nonfinite totals are excluded; genuine zero/negative totals
remain valid. Future weeks/observations and other seasons/rules are excluded.

The research simulation can use these full provider totals as a fallback
when component history is unavailable, including K/DST and rookies. At least
eight prior scored weeks are still required. No historical leagues or rookie
priors are silently pooled to satisfy that threshold. Provider totals are
not independently reconstructed boxscores or validated ROS models.

Player blockers now include names, explicit reasons and available platform
history counts. Explicit Active/Healthy/Normal labels no longer count as
injuries. Invalid projection/sample numbers fail closed. Recipe fingerprints
include the new history and simulation modules.

Remaining: ESPN scored-history collection; approved historical scoring-rule
bindings for older leagues; prospective evaluation and correlated scoring.
This change does not assert that current full-lineup win probabilities have
become available.

Validation: 648 tests passed, one skipped, 20 live tests deselected. Deployed
API/worker/beat; two worker-process runs succeeded. The first collected one
eligible completed week for Warriors and the second correctly collected zero
within the daily refresh interval. Aubrey, Bates and Baltimore each gained
one scored observation. Green Bay had no recorded provider total in that
week; this stays missing, not zero. A league matchup feed does not guarantee
coverage of every unrostered player/team. Full-lineup simulation remains
withheld with explicit player-level blockers.
