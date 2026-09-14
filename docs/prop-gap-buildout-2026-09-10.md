# Verified prop-gap buildout

Deployed explicit ESPN fumblesLost -> fumbles_lost mapping for NFL/NCAAF.
Missing rows, empty tables and absent totals do not establish individual zeros.
Fresh official final-result observations retain identity, participation, atomic
write and correction-confirmation gates. A bounded live refresh covered one NFL
and six NCAAF finals: 20 new NCAAF result rows, zero NFL rows, no deferred fetches
or unmapped identities. This does not yet qualify a fumbles prediction model.

Exact observed-component backfill now supports both football sports and excludes
player-games with pending corrections. No additional complete composites were
available in this sample; missing rushing/receiving components were not invented.

Added explicit model requirements for period/each-period, first/last scorer,
comparative game-high and ambiguous fantasy/total-TD markets. They cannot become
actionable through the generic full-game model, even if incidental history exists.
The requirements are fingerprinted in policy/model versions and exposed in
result-completeness counts and review samples. They are work classifications,
not claims that those dedicated models have been implemented.

At validation, NFL missing-stat expectations comprised 106 period-model, nine
settlement-rule, 18 play-order, 13 comparative-model and 35 boxscore/component
review cases. NCAAF: 30, 93, 189, 60 and 285 respectively. Many composite gaps
reflect missing component/participation evidence, not a failed sum operation.

56 regression tests passed. Live authenticated completeness and health endpoints
returned successfully. No candidate parameters promoted; no remote access edits.
Next work: verified play-by-play completeness/period clocks and explicit
bookmaker settlement semantics before pricing or grading special markets.
