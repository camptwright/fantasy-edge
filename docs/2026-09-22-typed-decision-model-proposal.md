# Typed decision models (Jev / Laya) — experimental proposal

Research spike requested: evaluate lightweight typed-decision models —
TypeSafe AI's **Jev** and the open-source **Laya** — for use in Fantasy
Edge, starting in `/experiments`, moving into the betting and fantasy
sides only if the existing promotion gate clears them.

## What these actually are

Both launched within the last week (Jev 2026-09-15, Laya three days later
as an open-weight response). Neither is a chatbot. They're a new category —
"System One" / decision models — that take a text `state` plus one or more
typed questions and return **numbers, not prose**:

- **Noul** (boolean) — calibrated probability a statement is true
- **Choice** — a probability distribution across a closed set of options
- **Score** — a value on an ordered numeric scale

No explanation, no reasoning, no hallucinated arithmetic — which is exactly
the failure mode B-05 in the original audit found in this app's old Ollama
narrative ("model probability (0.5663) is lower than the implied
probability (0.4255)" — it wasn't). These models structurally cannot make
that mistake, because they never emit a sentence.

| | **Jev** | **Laya** |
|---|---|---|
| Maker | TypeSafe AI (proprietary) | Convai Innovations (Apache 2.0) |
| Deployment | Hosted API, `api.typesafe.ai` | Self-hosted, weights on Hugging Face |
| Size | Undisclosed | 421M (English) / 322M (multilingual) |
| Cost | $0.042 / M input tokens, output free | $0 after infra |
| Zero-shot quality | Good — usable without any fine-tuning | Weak — near-baseline until fine-tuned |
| Calibration (ECE) | ~0.14–0.25 reported | ~0.08–0.21 reported, varies by fine-tune |
| Latency | 150–280 ms (API round trip) | 5–33 ms locally (Apple Silicon MLX/Core ML) |
| Wide option sets (20+) | Handles well (0.870 on 77-class benchmark) | Degrades badly (0.425 on same benchmark — fixed token budget shared across options) |
| Data leaves the Mac mini | Yes | No |

Benchmark numbers vary between independent write-ups depending on whether
Laya was fine-tuned, so treat the table as directional, not authoritative —
the app's own walk-forward harness is what should actually decide this, not
someone else's blog post.

## Fit for this app: strong for evidence classification, wrong for the probability engine

The betting side's whole architecture is built around *quantitative*
estimation — Elo ratings, logistic regression, walk-forward Brier scores —
fitted directly to the app's own 3.2M-row result history. A general-purpose
text classifier fine-tuned on synthetic data is not a substitute for that,
and Laya's own benchmarks say so: zero-shot it barely beats a majority-class
baseline (0.362 vs 0.461) on the reference task, and even fine-tuned it's
being compared against text-classification benchmarks, not calibrated
sports outcomes. **Do not use either model to replace Elo, the totals
model, or the walk-forward NFL predictor.** That's not what they're for,
and swapping a validated numeric model for a generic classifier would be a
regression, not an upgrade.

Where they fit is the large amount of **unstructured text this app already
collects and explicitly declines to convert into a number**:

```
src/data/espn_injuries.py:3       "never converted into a numeric [adjustment]"
src/services/injury_evidence.py:75 'used_for_numeric_adjustment': False
src/services/lab_availability.py:18 'participation_probability': None, 'used_for_numeric_adjustment': False
src/services/player_features.py:96 'used_for_numeric_adjustment': False
src/services/context_readiness.py:57 "never a numeric adjustment or injury/lineup confirmation"
```

That's five separate files carrying the same deliberate doctrine: ESPN
injury reports and RSS headlines are archived as *evidence*, never turned
into a probability, because the report text is unverified and a wrong
guess is worse than an honest "unknown." That constraint should not be
punched through by fiat. But `lab_availability.py` already has a
`participation_probability` field sitting at `None`, waiting for exactly
this kind of calibrated input — **if it earns its way in through the same
gate the props pipeline now uses.**

## Where a typed decision model can plug in, concretely

1. **Availability classifier (the headline use case).** Noul question over
   each archived injury report: *"Given this report, will this player
   appear in their next scheduled game?"* Score it against real outcomes —
   `player_game_stats` already tells you whether they played. Run it
   through `model_review.py`'s paired evaluation against the current
   baseline (`availability_flag()`'s crude string match in
   `fantasy_values.py`: `value not in ('', 'ACTIVE', 'HEALTHY', 'NORMAL')`).
   If — and only if — it clears the same bar the prop-validation work just
   built (fresh grading, 200+ independent cases, version-bound approval,
   SHA-256 fingerprint), `lab_availability.py`'s stub gets filled in.

2. **News severity triage.** Score question over archived headlines in
   `news_evidence.py`: *"Does this headline indicate a status change
   material enough to surface to the user?"* This doesn't touch a forecast
   at all — it's a display-priority filter sitting entirely upstream of the
   probability pipeline, so it can't violate the numeric-adjustment
   doctrine even in principle.

3. **Identity/alias disambiguation.** Choice question to resolve ambiguous
   player/team name matches in `src/ingest/identity.py` and
   `src/services/player_identity.py`. This is squarely a classification
   task (pick the right entity from a short list), it's what B-03 found to
   be the largest single blocker in the props pipeline
   (`unlinked_event`/`event_not_pregame`), and it carries zero forecast
   risk — a wrong disambiguation just means a quote stays parked, the same
   failure mode that already exists today.

4. **Ops triage (lower priority).** Categorizing `ingestion_runs.detail`
   failure strings turned out not to need this — a spot check found them
   already structured (`RuntimeError: parlay HTTP 503`), trivially
   regex-classifiable. Not worth the model call.

## Deployment: follow the Ollama pattern, don't fight Docker

Docker containers on macOS run inside a Linux VM (Lima) with no path to
Metal or the Neural Engine — this is exactly why `OLLAMA_BASE_URL` in
`.env` already points at `http://host.lima.internal:11434` instead of a
container name. Ollama runs on the host, not inside Compose.

Laya's Apple Silicon ports ([laya-mlx](https://github.com/mizorewww/laya-mlx),
[laya-coreml](https://github.com/mizorewww/laya-coreml)) need the same
treatment: 5–14 ms decisions only materialize running natively on the Mac
mini's GPU/ANE, not inside a container (CPU-only in a Linux container was
independently benchmarked at ~49 seconds per query — unusable). The plan:

- Run `laya-mlx` (or `laya-coreml` for the Neural Engine path) as a
  host-side process, same tier as Ollama.
- Add `LAYA_BASE_URL` to `.env` and `config/settings.py`, pointed at
  `http://host.lima.internal:<port>`, mirroring `OLLAMA_BASE_URL` exactly.
- Celery tasks call it over that bridge, same as any other worker HTTP
  call — no new constraint class, no Docker GPU passthrough to solve.

Jev needs none of this — it's a plain HTTPS API call, useful specifically
*because* it requires zero local infrastructure.

## Phased plan

**Phase 0 — experimental spike, days not weeks.** Pull a sample of already-
archived injury reports where the outcome is now known (join
`injury_evidence` archives to `player_game_stats`). Score them zero-shot
with Jev (near-free — the whole backtest sample will cost cents) *and*
zero-shot Laya, side by side, through the existing Brier/reliability
harness. This answers the only question that matters before investing in
local infrastructure: is report text classifiable at all above the current
crude heuristic. If neither beats the baseline, stop here — that's a valid
result and cheaper to learn in an afternoon than after building the MLX
pipeline.

**Phase 1 — if promising, stand up Laya locally.** Fine-tune on the app's
own archive (Convai publish a ~4-hour free-GPU Kaggle recipe for this),
pin the checkpoint, fingerprint it the same way `model_version.py`
fingerprints everything else, deploy via `laya-mlx` on the host. Re-run
the same walk-forward evaluation on the fine-tuned checkpoint.

**Phase 2 — betting side, gated.** A validated availability probability
becomes a new `exclusion_reason` in `signal_eligibility.py`
(e.g. `availability_probability_below_threshold`), not a silent multiplier
on the projection — same "block, don't adjust" discipline already in place
for the EV/Kelly checks. Identity disambiguation wires into
`prop_events.py` to reduce `unlinked_event` parking.

**Phase 3 — fantasy side, gated.** The same availability probability fills
`lab_availability.py`'s `participation_probability` stub and upgrades
`availability_candidate` from an opaque status string to a real confidence
tier inside the FF-03 fallback ladder recommended in the original audit —
*"reported_questionable, 34% expected to play"* instead of a flat flag.

## What this is not

Not a reason to reopen the LLM-narrative question B-05 just closed. Not a
replacement for the Elo/logistic probability models or the fantasy
distribution work still pending (F-R1/X-R1 from the original audit) — those
stay quantitative, fitted to this app's own history. And nothing here
should bypass the promotion gate the team built two days ago for exactly
this reason: an unvalidated model output reaching a live number. Phase 0 is
cheap, bounded, and answers the real question before anything gets
promoted.
