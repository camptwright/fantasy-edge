# Waiver retention review

The preview weekly optimizer can pair a defensive streaming gain with dropping a
bench quarterback. Its objective values unstarted slots, not long-term roster
cost. This sweep does not change that objective or claim improved forecast accuracy.

The workspace API now attaches a research-only status and retention warnings to
each eligible pair: missing full ROS evidence, higher conditional ROS on the
proposed drop, cross-position depth, missing position, and injury designation.
Even complete conditional ROS estimates never qualify a drop recommendation.
The preview labels each pair “Research … for …” and prominently displays “Drop
decision unresolved.” Older response shapes receive a conservative UI fallback.

Verification: 55 workspace backend tests, 35 frontend tests, TypeScript, lint,
generated response-contract check and Docker production build passed. Preview API
and dashboard deployed; legacy API/dashboard and prediction workers unchanged.
Browser verification at localhost:13001 confirmed the Bo Nix / Jets pair shows
missing ROS and positional-depth warnings beside the 1.4-point weekly gain.
An initially unavailable checkpoint recovered through the normal refresh link.

Remaining: model and evaluate roster retention/opportunity cost, compare alternative
drops without arbitrary tie selection, incorporate future bye-week depth and
league-specific keeper/dynasty contracts. These warnings improve interpretation,
not the underlying weekly optimization, ROS qualification or model accuracy.
