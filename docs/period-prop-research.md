# Period and scorer research integration

## Delivered

The read-only authenticated `/experiments/football-props` API exposes historical
coverage, separate evaluation metrics, partial bookmaker/product rules and
promotion blockers. It reads only a compact immutable status artifact, not the
full play history. The Experimental dashboard panel consumes this endpoint;
its source is implemented and type-checked but the running dashboard was not
rebuilt, preserving the ongoing remote-access deployment.

Run the offline history job with:

```sh
RAW_ARCHIVE_DIR=/absolute/research/directory .venv/bin/python -m scripts.build_period_research
```

Requires the existing `offline` dependencies. Fetches public nflverse 2024/2025
play-by-play, schedules and player statistics, archives selected original input
fields with hashes, and produces immutable label/evaluation/status artifacts.
It does not modify production stats, scheduler jobs, quotes, or serving models.
Source: https://nflreadr.nflverse.com/reference/load_pbp.html and
https://nflreadr.nflverse.com/reference/load_player_stats.

## Coverage measured, not assumed

| Season | Scheduled finals | Timeline passes | Period-family reconciled games | Scorer-reconciled games |
| --- | ---: | ---: | ---: | ---: |
| 2024 | 285 | 259 | 168 | 239 |
| 2025 | 285 | 261 | 194 | 242 |

Period families: passing yards, receiving yards, rushing yards, receptions and
carries. Four quarters and regulation halves yield 30 targets; first/last
touchdown scorer add two. Overtime is reconciled in full-game totals but never
silently added to fourth-quarter or regulation second-half labels. These are
provider-neutral research labels, not bookmaker settlement labels.

Games are rejected for missing boundaries, ambiguous play order, missing or
regressing clocks, missing quarters, final-score mismatches, invalid box player
identities, or stat-family mismatches. Lateral plays block period families until
allocation is validated. Some source boxscore rows have null player IDs; these
are intentionally not guessed or silently discarded. Scorer reconciliation
includes defensive/special-team touchdowns, not just offensive listed players.

This is **same-provider reconciliation**, not independent historical validation.
There are 570 games in the input inventory, not 570 validated games. NFL coverage
is incomplete; NCAAF is not covered by this new historical importer.

## Separate evaluation

The fixed research control uses up to 20 prior eligible games; the candidate
uses eight. At least eight earlier observations are required. Histories update
after every game on a date has been predicted, avoiding same-day outcome leakage.
2024 provides warm-up and 2025 is the evaluation season. Metrics include MSE for
period quantities, Brier for scorer indicators and game-clustered error deltas.
This compares two research models, **not** a production full-game baseline.

Final player-stat records define a conditional historical participation cohort;
they must not be used as pregame roster evidence. Historical corrections lack
publication snapshots. No historical period prices are provided, so these
metrics establish neither betting returns nor a calibrated over/under edge.
Scorer estimates are marginal, not a jointly normalized competing-player model.

## Settlement registry

`config/football_settlement_rules.json` keeps source URL, review date, product,
sport and unresolved clauses. `settlement_lookup` requires exact book/product
identity; unknown products never inherit another product's policy.

- Bovada standard football: https://www.bovada.lv/help/common-faq/football-betting-rules
- Bovada Prop Builder: https://www.bovada.lv/help/sports-faq/prop-builder-faq
- DraftKings: https://sportsbook.draftkings.com/help/sport-rules/football?sf260608803=1

These are partial evidence profiles, not approved settlement contracts. Confirm
jurisdiction, effective dates, quoted product, no-TD/unlisted-player treatment,
overtime exceptions and injury/abandonment rules before enabling settlement.
Do not apply present-day rules retroactively to historic bets.

## Remaining promotion work

1. Repair excluded historical families with independently sourced final boxes,
   verified identity crosswalks and official gamebooks; extend NCAA coverage.
2. Capture exact product/jurisdiction rules alongside each prospective quote.
3. Establish pregame eligible-player populations, active/inactive and snap
   participation evidence; never replace missing participation with zero.
4. Evaluate period count/yardage probability distributions at captured lines and
   a normalized scorer model including unlisted/no-TD outcomes.
5. Run prospective shadow evaluation and review promotion against the retained
   baseline. No automatic promotion is implemented here.

Verification: 47 focused tests passed; dashboard TypeScript check passed;
deployed API research endpoint and health both returned 200. Serving model and
policy fingerprints remained unchanged. Dashboard panel awaits deployment.

## Next increment: excluded families, NCAA pilot, prospective capture

Lateral exclusions now apply to affected families, rather than discarding all
families for every lateral. The public nflfastR field documentation distinguishes
receiving and rushing lateral allocation:
https://nflfastr.com/reference/fast_scraper.html.
Unidentified player rows, score inconsistencies and affected lateral families
remain blocked. Recomputed NFL passing/receiving/reception coverage is 171 games
for 2024 and 195 for 2025; rushing/carries coverage is 181 and 204 respectively.
This is still same-provider reconciliation, not independent validation.

`python -m scripts.collect_ncaaf_period_history` collected ten final games from
existing archived summaries using public ESPN Core. Six passed timeline checks;
none is fully validated. All have unresolved stat/attribution evidence. This is
a bounded completed-game pilot, not a complete NCAA season import. Its reports
are visible in `/experiments/football-props` under `ncaaf_history`.

`settlement_binding.bind` creates an immutable hash of quote identity, exact
book/product/jurisdiction/market, capture time and rule contract. Unknown product,
partial rules, missing source snapshots or mismatched effective intervals fail
closed. Current quote storage has no authoritative product/jurisdiction fields;
those remain explicitly missing, not inferred from a provider/book suffix.

The separate empirical period probability candidate emits over/under/push
probabilities using at most twenty prior games, minimum eight, with fixed
Dirichlet smoothing. Half-point lines have zero push mass. Histories must have
been published before capture and games must precede the capture date. Scorer
markets require a future joint model and are deliberately not priced by this
candidate. Current coverage is Q1/Q2/Q3/first-half supported NFL statistics;
ambiguous Q4/second-half overtime settlement is outside capture scope.

`python -m scripts.capture_period_shadow` runs a read-only bounded capture.
The existing fifteen-minute forecast task now also captures these quotes in a
fresh worker DB context, with failures isolated from baseline forecasts. Raw
line/price, history hash, code hashes, binding blockers and probabilities are
archived in `period-shadow-forecasts`. This does not grade bets or place orders.
The initial live capture found zero eligible pregame period quotes. No successful
prospective probability or performance result is claimed from that empty run.

Forty-eight focused tests passed. Remaining: independent history corrections,
broader NCAA data, verified product/jurisdiction metadata and full rules,
prospective quote cohorts/results, and normalized competing-scorer evaluation.

## Local follow-up: verification and resumability

The settlement binder now requires actual archived source bytes matching a
SHA-256 digest, explicit sport identity, required settlement clauses and a valid
effective interval. A caller-supplied `verified` flag or arbitrary digest alone
can no longer make a binding ready. Rule snapshots are detached from mutable
caller dictionaries. Product/jurisdiction input is still required from the user;
no profile has been approved or deployed as a complete contract.

The period probability candidate now rejects boolean, fractional and non-finite
history outcomes rather than silently generating incomplete probability mass at
half-point lines.

The college collector now resumes across earlier successful reports, skips
unchanged summary hashes and revisits changed summaries. The ten-request cap
applies to each run, not cumulative history size. Existing reports without
hashes can recover them from the original archived summary. This enables broader
collection instead of repeatedly fetching the same latest ten games.

`scripts/audit_independent_nfl_history.py` is a resumable 20-request cross-feed
audit using public nflverse GSIS/ESPN crosswalks and ESPN final summaries.
Comparisons verify event IDs, Eastern-local game dates and final scores;
conflicting identity mappings are excluded. Explicit values, disagreements and
missing-source evidence are separate states. Neither absent categories nor
unmapped athletes are converted to zero. This script has not been run live yet.

`src/services/joint_scorer_shadow.py` implements regulation-only piecewise
competing-Poisson probabilities with four quarterly rate maps. First/last scorer
probabilities each sum to one including explicit other-scorer and no-touchdown
outcomes. This is a tested mathematical component, not a trained or evaluated
production model; verified pregame rates/universe and overtime contracts remain
required. It is intentionally not wired into recommendations.

Live provider checks and Docker deployment were blocked by the approval
service's usage limit during this increment. These changes are local only;
no new independent-validation counts or deployed-model changes are claimed.
