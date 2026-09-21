# Keeper and specialist validation work

## Keeper pricing

The live Sleeper league `1398509004950376448` specifies type 1 and
`max_keepers: 1`. It does not establish draft-round/salary cost, annual escalation,
retention limits, or eligibility. These rules were requested from the owner.
Redraft and dynasty market indexes must not be blended and labeled keeper prices.
Pricing requires an explicit opportunity-cost unit (pick value or auction dollars),
the player's retention cost in that same unit, and a verified rule set.

## Kicker research

`scripts.evaluate_fantasy_specialists` uses archived 2024 and 2025 nflverse player
statistics. Kicking fields are scored against each league's scoring settings.
The fixed candidate is 75% trailing-20-game mean plus 25% trailing-four-game mean,
requiring eight prior complete observations. The baseline is the trailing-20 mean.
2025 outcomes are held out sequentially: no current/future outcome enters its
own forecast. Duplicate player-games are rejected. Missing categories are not zero.

There were 459 evaluated player-games from 38 kickers per league, with 84 excluded.
Baseline/candidate MAE respectively:

- Dynasty: 3.9345 / 3.9482.
- ESPN: 3.9292 / 3.9421.
- Keeper league kicking scoring: 3.5922 / 3.6042.

The candidate lost in all three formats. Retain the baseline; no model promotion.
This is retrospective per-game kicking-component evaluation, not independent
prospective ROS validation. Corrected archives may not reflect information
available at the original prediction time. Participation, trick-play scoring,
injury recovery and full-season roster retention are not modeled.

Rookie and DST models remain unfinished: rookies need verified draft/experience
cohorts and prior-only opportunity features; DST needs reconciled team defense
scoring, including platform-specific points-allowed and return-TD treatment.

## Weather and settlement

Official venue research was continued, but no new coordinate/roof binding was
verified. Older stadium articles and venue names alone are insufficient for a
current event, especially stadium replacements and retractable roofs.

The current generic DraftKings football URL rendered navigation and a
jurisdiction-specific footer rather than sufficient rule clauses. A successful
HTTP response cannot qualify the contract. A redacted real quote/slip showing
book/product, market wording, timestamp and account jurisdiction was requested.
No jurisdiction, quote identity, roof state or historical effective date was
invented. Existing serving gates remain in force.
