# Fantasy navigation follow-up

Main desktop/mobile header links now preserve the selected league query parameter, matching the fantasy submenu. Active-state matching no longer marks Fantasy and Matchup simultaneously; active links expose aria-current. Root navigation has a Suspense boundary for search parameters.

Local and container production builds passed. Five fantasy view/request-model regression tests passed against the isolated test database (initial sandboxed DB access was denied; rerun with network permission passed). Dashboard and local-preview source/artifact fingerprints match. Previous preview retained for rollback.

Live decision-model requests returned HTTP 200 in 0.18, 0.11 and 0.22 seconds for the three configured leagues. No own-roster player returned a null decision estimate in those responses. This does not establish all-player coverage or validated probabilities. Site-wide browser latency profiling, missing historical evidence and numerical model improvements remain open. No prediction math or eligibility gates changed.
