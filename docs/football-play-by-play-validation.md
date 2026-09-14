# Football play-by-play validation — research only

The final-result collector now archives an ESPN timeline validation report beside
each NFL/NCAAF observation. It writes no period/player/scorer facts and does not
enable period or scoring-order predictions. Existing special-market serving gates
remain active. No raw private-host links are followed.

Checks include requested completed event, duplicate/conflicting IDs and sequence
numbers, regulation start/end markers, clock/period monotonicity, cumulative-score
monotonicity, final-score equality, quarter-score reconciliation and touchdown
index consistency. Overtime is held for explicit rules. Passing a timeline check
does not prove all non-scoring plays are present. Player totals are not yet derived.

Bounded archived-data audit: 20 unique games, two passed the timeline checks (NFL
401872656 and NCAAF 401858212). Eighteen had ambiguous duplicate sequences; other
overlapping blockers included clock/score regressions and missing start evidence.
Inspection confirmed at least one repeated sequence referred to a reviewed punt
and a same-clock timeout. These flags are unresolved ordering/coverage issues,
not proof that ESPN omitted those plays. Do not break ties by invented chronology.

Sampled summary plays expose team references but no structured player role IDs;
abbreviated prose is not an identity crosswalk. TD play ordering is not a claim
about the individual first/last scorer. Neither thrower nor scorer is guessed.

Next requirements: public structured player attribution, reviewed/nullified-play
semantics, confirmed non-scoring play coverage, player-level boxscore reconciliation,
NFL/NCAAF overtime differences, bookmaker first/last-scorer settlement rules and
prospective evaluation. Research reports retain payload hashes/source archives.

Run `python -m scripts.audit_football_pbp` in the worker to audit up to 20 unique
games from at most 2,000 recent saved result observations, without provider calls.
Reports: raw/football-pbp-validation and raw/football-pbp-audit.
