# Structured football reconciliation — 2026-09-10

Research-only implementation: `src/services/football_structured_pbp.py` and
`python -m scripts.audit_structured_football`. No settlement facts, projections,
or promotion gates are changed. The script reads bounded archived samples and
archives comparisons; it does not schedule additional provider requests.

Public ESPN Core feeds supply athlete references and participant roles. College
inline participant statistics are full-game totals and are intentionally ignored.
The complete single-page Core list supplies candidate ordering, checked against
quarter clocks, scoring index, period totals and final scores. Duplicate sequence
numbers are not treated as globally unique; ambiguous tied scoring events remain
blocked. Multi-page/incomplete payloads and wrong-event references fail closed.

Initial archived sample:

| Event | Matched player/stat totals | Mismatched | Missing derived | Timeline |
| --- | ---: | ---: | ---: | --- |
| NFL 401872656 | 70 | 2 | 6 | Passed |
| NCAAF 401858438 | 70 | 7 | 0 | Score regression |

NFL mismatches are one player's rushing attempts (6 versus 7) and yards (46 versus
47). Six missing derived fields are zero-catch receivers: their final zeros were
not copied into play-derived totals. College mismatches involve rushing attempts,
rushing yards and one passing attempt. Penalty/fumble evidence and college sack
allocation remain unresolved rather than guessed from play prose.

The original audit archive is
`football-structured-reconciliation/20260910T231501.098221-304903735f2f4692b340322ab5ef2157.json`.
It retains source archive paths and individual comparisons.

Ten focused tests pass (structured reconciliation and existing timeline tests).
Remaining work: per-play statistical evidence for penalties/fumbles/sacks and
defensive-touchdown passing attempts; college score-regression adjudication;
broader archived-game validation; settlement-specific period/scorer rules and
prospective model evaluation. Exact full-game matches do not prove correct
within-game allocation. All period candidates remain non-serving research data.

The research scripts were copied into the current worker for the sample audit;
repository source is persistent, but no production image rebuild or automated
Core collection was performed in this increment.

## Additional per-play evidence

`python -m scripts.collect_football_play_evidence` follows only explicit public
`playStatistics` references for ambiguous offensive plays. It caps requests at
30, rejects redirects/foreign hosts and archives responses separately. Cumulative
splits, wrong player/event/play IDs, incomplete categories, duplicate values and
non-finite values are rejected. All relevant offensive roles must resolve before
any evidence from that play is added; inline college game totals remain ignored.

The bounded run made one public request. NFL play 401872656320 explicitly records
Drake Maye's one-yard rushing attempt despite its penalty flag. The new NFL audit
has **72 matched totals, zero mismatches, six missing derived receiving-zero
totals**. College remains 70 matched/seven mismatched. Neither a missing athlete
nor an absent stat is replaced with a final-boxscore zero.

New archive:
`football-structured-reconciliation/20260911T014942.324649-2184772495604c5e9e5749a14b26af28.json`.
The college score regression is present in both Core and summary records:
kickoffs 401858438163 and 401858438476 carry premature home scores. No independent
correction was found, so neither ordering nor scores were silently repaired.

Twenty-nine focused tests pass. Reports now distinguish full-stat-family total
reconciliation from serving readiness. Period/scorer serving remains blocked by
unresolved play evidence, market settlement rules, insufficient validated history,
and the absence of an evaluated period/scorer prediction model. Removing the
generic gate would incorrectly route these markets through the full-game model.
No serving/model version change or production image rebuild was made.
