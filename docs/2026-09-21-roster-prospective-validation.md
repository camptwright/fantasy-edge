# Roster corroboration and prospective validation

## Roster evidence

The new six-hour task archives current rosters for teams with scheduled games
in the next seven days. NFL, NCAAF and NBA use ESPN team-roster endpoints;
MLB uses the official Stats API active roster, an explicit observation date,
and exact team identity. NHL coverage is not claimed by this collector.

Evidence is joined using sport-scoped provider athlete IDs, never names.
Snapshots retain provider payloads, source URL, SHA-256, canonical team,
season and observation time. Evidence expires after 12 hours. Failed refreshes,
conflicting team memberships, unknown IDs, changed seasons and wrong teams
remain unresolved. No historical result or canonical team assignment is
rewritten. Roster membership is not a confirmed starter, role or game-day
availability; the existing injury/game-availability checks still apply.

The first production refresh corroborated 111/112 teams. Inspection of the
remaining MLB response found `fullRoster` included organization-wide records
and duplicate IDs. The collector was tightened to `active`, which returned
28 active players for that team; organization-wide snapshots cannot satisfy
the final MLB corroboration policy.

Exact live provider-ID checks corroborated Terrance Ferguson with the Rams,
and Darnell Mooney and Theo Johnson with the Giants. These are observed roster
facts, not name-based guesses or retroactive participation certifications.

## Prospective protocol v2

The old NFL setup had two structural dead ends: 200 independent games in a
30-day window, and an unchanged baseline required to outperform itself.

New captures explicitly freeze `verified-first-capture-season-aware-v2`:

- Football (NFL/NCAAF): 120 collection days, then seven grading days.
- Other covered sports: 30 collection days, then seven grading days.
- Still at least 200 independent games; game-cluster uncertainty, paired
  outcomes and missing-result checks are unchanged. No sample threshold was
  reduced and no model was automatically approved.
- The unmodified serving baseline is compared against the paired market
  benchmark. Candidate/override and shadow models must improve against the
  retained baseline and the market. Merely being equal to the retained
  baseline is not accepted as candidate improvement.
- Only protocol-verified observations start the evaluation window. Earlier
  unverified research stays archived and can be statistically graded, but is
  excluded from promotion evidence. The earliest verified pregame capture
  takes priority over an earlier unverified one, without consulting outcomes.
- Exact event binding and fresh roster corroboration are required. Integer
  lines remain outside the baseline promotion cohort until push-aware pricing
  exists. Research capture continues independently of recommendation approval.
- Legacy archives keep the old protocol; they are not retroactively certified.
  Capture, feature, roster, grading and policy code are included in the cohort
  fingerprint. Approval additionally requires the exact fixed-window decision
  digest and a fresh successful grading run.

## Operational status

The validation page exposes roster-corroborated quote counts and verified
prospective-capture counts. The roster task is scheduled every six hours;
forecast capture remains every 15 minutes and grading every 30 minutes.

At initial live verification, neither prop provider could refresh quotes:
the configured daily reservations were exhausted (SGO 60/60; Parlay 24/24).
There were no fresh NFL quotes at that moment. Limits were not increased or
bypassed; scheduled collection resumes after the UTC budget reset. Fresh
quotes and completed prospective outcomes remain prerequisites, not missing
software that can be replaced with fabricated evidence. A statistically
validated model cannot be declared immediately upon deploying this protocol.

## Verification

The final collector corroborated **112/112 teams**, with zero failures, on two
consecutive production runs in the same process. Forecast capture succeeded
twice (342 research records per run), and grading succeeded twice with identical
counts: 20,763 graded, 28 pushes, 1,357 pending, 1,341 missing results and 1,159
invalid-timing records across existing historical cohorts. Those totals are
not evidence of 20,763 independent or newly verified observations.

Full default suite: **637 passed, one intentional skip, 20 live checks excluded**.
Dashboard build, TypeScript check and localhost validation-page HTTP 200 passed.
Tests cover exact roster IDs/team/season, stale/conflicting evidence, MLB active
roster scope, 120-day football windows, market-baseline versus retained-baseline
comparison, and exclusion of unverified observations from promotion statistics.
