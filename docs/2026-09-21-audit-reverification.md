# Audit reverification — 2026-09-21

Independent reverification of [the 2026-09-20 full-stack
audit](2026-09-20-full-stack-audit.md) against the live stack, after four
remediation commits (`49c0df5`, `f8a7b46`, `4461f71`, `9d5ee8e`). Every claim
below was checked directly against the running containers and Postgres — the
team's own [remediation](2026-09-21-audit-remediation.md),
[prop-validation](2026-09-21-player-prop-validation.md) and
[roster-validation](2026-09-21-roster-prospective-validation.md) notes were
read in full but not taken at face value.

Rendered version:
https://claude.ai/code/artifact/12f271af-af16-42a9-931d-4a55800c69d9

## Status tracker

7 of 19 tracked findings fixed, 2 partial, 10 open. (Corrected 2026-09-22:
this line originally read "10 fixed, 2 partial, 7 open", which contradicted
the table below.)

| ID | Finding | Status | Verified |
| --- | --- | --- | --- |
| F-00 | ESPN rejects multi-day date ranges | **Fixed** | Ranges expanded to single-day fetches; live ingestion succeeding |
| F-01 | One sport's failure kills the other two | **Fixed** | Per-sport try/except; NFL+NCAAF+NBA all synced in the last hour |
| F-02 | Silent failure, no alert fired | **Fixed** | Root cause was alert delivery (HTTP 400), not detection; now fails loud |
| F-03 | Scheduled games carry 0–0, not NULL | **Fixed** | 0 scheduled games with non-null scores, live query |
| B-01 | Model pointed at Pinnacle instead of soft books | Open | Architecture unchanged — the strategic fix |
| B-02 | Failed-gate models serving live signals | **Fixed** | New eligibility gate; live `/signals` 342 rows, 0 actionable |
| B-03 | Props never join to games | Partial | Exact event binding built; correctly 0 actionable pending approved model |
| B-04 | Underdog / PrizePicks sources dead | Open | Still last capture 7–9 Sep, untouched |
| B-05 | LLM narrative states false things | **Fixed** | LLM removed entirely; deterministic templated summaries |
| B-06 | No closing-line history for CLV | Open | Live capture still 17 days (04–21 Sep) |
| FF-01 | Two fantasy engines disagree | Open | No fantasy-side commits since the audit |
| FF-02 | Optimiser maximises points, not win% | Open | Unchanged |
| FF-03 | Abstention has no fallback ladder | Open | `matchup.status: withheld`, unchanged |
| FF-04 | Advice window closed during live slate | Open | Still week 2, `weekly_decisions_open: false` |
| FF-05 | 3.2M rows of history feed nothing | Open | Pool coverage unchanged (~55% usable) |
| X-01 | No promotion path, lab model unshipped | Partial | A real, honest gate now exists — and correctly blocks promotion; still 0 rows in `model_artifacts` |
| X-02 | Neither model beats the market | Open | Unaddressed — same finding, still true |
| X-03 | Artifacts unwritten, grading on a bind mount | Open | Unaddressed |
| X-05 | Test suite unusable (179 errors) | **Fixed** | 636 passed / 1 failed (host-only), re-run live this session |

X-04 (nflverse/EPA revival) was framed as an opportunity rather than a
defect in the original audit and isn't tracked as pass/fail here; it remains
untouched (`nflverse` last ran 2026-09-04).

## What changed since the audit

### Closed — the outage (F-00 through F-03)

All four verified live. `src/ingest/espn.py` now has a `scoreboard_dates()`
helper that expands any range into individual `YYYYMMDD` requests before
hitting ESPN, deduplicating events across days. `src/scheduler/tasks.py`'s
`sync_espn` gives each sport its own DB session inside a `try/except`
instead of aborting the loop on the first failure.

```
SELECT source, status, count(*) FROM ingestion_runs
WHERE source LIKE 'espn%' AND started_at > now() - interval '90 minutes'
GROUP BY 1,2;

 espn_nba   | succeeded | 18
 espn_ncaaf | succeeded | 18
 espn_nfl   | succeeded | 18
```

NCAAF has 26 upcoming games again (was 0). 281 existing 0–0 placeholder
rows were cleared; live query for scheduled games with a non-null score now
returns 0.

**Correction to my original diagnosis of F-02**: I assumed the health check
threshold was relative rather than absolute. The team's investigation found
the actual break was alert *delivery* — ntfy returning HTTP 400 while the
health task still reported success — not a detection gap. Fixed with a
UTF-8 byte bound on message length and delivery-status propagation. Their
diagnosis was more accurate than mine.

### Closed — signal safety (B-02, B-05)

`src/services/signal_eligibility.py` is new. It requires positive EV,
positive Kelly, a valid probability, a pregame kickoff, a fresh quote
(≤45 min), *and* a version-bound model validation matching sport/market/model
identity within 7 days. Live `/signals`: 342 rows, 0 actionable, every one
carrying an explicit `exclusion_reason`.

This is correct behavior, not a regression: the legacy `CalibrationReport`
has no model fingerprint, so it can't authorize a specific serving
configuration under the new gate.

`src/services/recommendations.py` no longer calls an LLM at all — its
docstring now reads *"Deterministic, quote-bound numeric summaries. No LLM
or external calls."* This goes further than my B-R4 recommendation, which
only asked to template the existing narrative around pre-computed numbers.

### Partial — props (B-03) and model promotion (X-01)

Mid-audit on 2026-09-20 I observed `/props/best` return 20 actionable items
where it had returned 0 the day before, and flagged it in conversation as
"better than reported." That was premature. The team's investigation
(`docs/2026-09-21-player-prop-validation.md`) found those large edges came
from an all-history Normal baseline for players with as few as 14–16 games
and **no verified current team** — Terrance Ferguson, Darnell Mooney and
Theo Johnson all lacked canonical roster assignment at the time.

The fix was not a join repair; it was a full identity-verification layer:

- Migration 0018 adds exact provider-event binding to quote liveness
  metadata — compares game UUID, sport, both teams and kickoff at serving
  time.
- A new roster-corroboration task (`src/services/roster_evidence.py`) hits
  ESPN/MLB roster endpoints on provider athlete IDs every 6 hours. First
  production run corroborated 111/112 teams; a second, tightened run hit
  112/112 after catching an MLB `fullRoster` vs `active` roster scope bug.
- `config/prop_validation_approvals.json` requires a fresh (≤2h) grading
  report, an exact cohort match, a closed prospective window, 200+
  independent games, a passing review, and an explicit approval matching
  model/cohort/sport/market/decision-SHA256.

`/props/best` is back to `{"items": []}` — correctly, this time. No prop
model has cleared the new bar; the approvals file is empty by design.

The same "build the gate, then let it correctly refuse" pattern applies to
X-01: a version-bound promotion protocol now exists end to end (code/model
fingerprinting, fresh grading, closed prospective window, paired review
against both the retained baseline and the market), but
`nfl_lab_logistic_v1` — the model my original audit recommended promoting
on the spot — has not been run through it. `model_artifacts` and
`model_predictions` remain at 0 rows, verified live. Building the gate was
necessary; using it to promote something is still open.

Their own remediation note states this explicitly: *"Published benchmark
comparisons and the audit's model promotion recommendation are not
sufficient evidence to bypass the real gate."* Correct call — my
recommendation to promote on four seasons of backtest alone was too loose
against their new bar.

### Closed — test suite (X-05)

Fresh full run this session, foreground, outside Docker:

```
636 passed, 1 failed, 1 skipped, 20 deselected in 35.14s
```

The single failure (`test_mlb_ingestion_is_restartable_and_idempotent`) is
an artifact of running on the host Mac rather than in the container — it
tries `os.mkdir('/mnt')`, a path that only exists inside the Docker image
per constraint #18 in `CLAUDE.md`. Not a real regression.

### Untouched

- **B-01** — the core strategic finding (price off the sharp market, bet
  the soft books) has no architectural change.
- **B-04** — Underdog last wrote rows 2026-09-07, PrizePicks 2026-09-09;
  neither has been revived.
- **B-06** — `team_market_lines` live capture still spans only
  2026-09-04 → 09-21, 17 days; CLV still cannot be computed.
- **FF-01 through FF-05** — zero commits touched
  `fantasy_decision_models.py`, `fantasy_values.py`, or the fantasy
  dashboard routes since the audit. Re-queried the same live league
  (`2016 Warriors`, week 2): `matchup.status` still `withheld`, `waivers`
  still `withheld_stale_or_started_week`, still week 2 with
  `weekly_decisions_open: false`.
- **X-02, X-03, X-04** — market-beating accuracy, artifact durability, and
  nflverse/EPA revival all unaddressed.

## Where this leaves things

What shipped today converts the app from *actively lying* (false EV, false
narrative, silent outage) to *honestly withholding* (correct zeros, real
gates, refused promotions). That's real progress, and fixing it first was
the right call — none of the strategic work is trustworthy on top of a
stack that can silently go dark for two weeks or recommend a −44% EV bet.

But it means the product still doesn't do the thing it exists to do: no bet
has been priced against a soft book, no fantasy lineup has a win
probability, and no lab model has reached production. The next unit of work
is unchanged from the original audit's B-R1 / X-R1 / F-R1, in that order.
