# Readiness fixes and model research

## Serving correctness

`quote_availability` records successful source confirmation independently of
immutable quote observations. Unchanged quotes refresh only this metadata.
Underdog full snapshots withdraw absent offers after a successful parse, with
source polling serialized by a PostgreSQL transaction advisory lock. Other
sources currently expire by timeout; explicit withdrawal is not yet universal.
Offers expire 45 minutes after the last confirmation. A failed feed cannot keep
an old quote eligible forever, and a healthy unchanged quote is not mistaken for
a stale price. Historical rows are not rewritten or deleted.

All actionable props require a known future kickoff, scheduled event, confirmed
available quote, sufficient variable history, and a price. Historical/unlinked
props remain inspectable but have no actionable EV or override. Latest prop
selection includes event identity. Team signals also require confirmed future
offers. Unknown-time fixtures remain stored, not silently deleted.

Custom parlays reject duplicate, contradictory, and all same-game combinations
until a joint model exists. Automatic parlays choose at most one leg per event.
Unknown IDs retain the existing explicit `skipped_legs` contract. Independent
events are still an approximation, not a guarantee of statistical independence.

Cached recommendation snapshots record their quote IDs. Serving withholds old,
unverifiable, changed, withdrawn or started-event narratives. No stale narrative
is overwritten; it simply ceases to be actionable. The next generation refreshes
it using eligible evidence.

MLB polls include three prior UTC days and up to 100 explicitly unfinished
fixtures, including known external IDs with unknown kickoff. Returned duplicates
are processed once, and existing final results do not increment ratings twice.
Very old unresolved events may still need exception review.

## Four improvement tracks

1. **Prospective evaluation:** immutable captures retain paired baseline and
   vig-removed market probabilities. Grading adds reliability bins, paired Brier
   and log loss, and the existing game-cluster bootstrap review. The evaluation
   protocol freezes the first capture's UTC date through the next 30 days, with
   seven additional days for grading. Missing outcomes, missing benchmarks,
   incomplete pairs, fewer than 200 independent games, or an open window block
   eligibility. Reports do not deploy models. Display scores weight individual
   observations; the review's Brier comparison weights games equally.
2. **Player context:** each eligible prop can archive historical and last-five
   means, variance, inactivity, observed opportunity/rate features, position,
   home/away and available opponent rating context. Features exclude unknown-time
   and future game outcomes. Available targets, attempts, minutes and plate
   appearances are used where recorded; receptions are explicitly labeled as a
   proxy, not targets. Opponent context is captured but not yet fitted into the
   numeric model. Confirmed roles, injuries, timestamped weather and news features
   remain missing. Historical boxscores lack publication timestamps; only the
   new immutable feature snapshots support prospective reproducibility.
3. **Distribution research:** fixed shadow recipes blend recent/observed-usage
   means with historical means, bounded to one baseline standard deviation of
   change. Count markets get Poisson or overdispersed negative-binomial candidates;
   kicking points additionally get a 3×FG + XP convolution when components exist.
   Push, Over and Under mass are explicit; graded binary probabilities condition
   on non-push. Kicking components currently assume independence. These recipes
   are research proposals, not trained or validated replacements. Recipe hashes
   are separate from serving fingerprints, and shadows never affect live EV or
   parlay recommendations or inflate serving outcome counts.
4. **Coverage/identity:** exact interceptions aliases share one outcome per
   player/event, preferring the canonical field; legacy odds remain immutable.
   Event matching recognizes exact configured team abbreviations without fuzzy
   identity or kickoff guesses. MLB ingestion now also records available plate
   appearances for future opportunity histories. Previously completed backfill
   markers are not silently erased to retrofit that field. All-sport coverage
   exposes actionability, blockers, canonical aliases, unique historical
   player-games, last result dates and examples of upcoming history gaps.

## Inspection and operation

- `/calibration/live`: serving results plus fixed-window prospective scorecards.
- `/calibration/research`: separately graded shadow candidate scorecards.
- `/calibration/coverage`: all-sport statistical and offer eligibility coverage.
- `/calibration/prop-readiness`: existing NCAAF view, now with actionability and
  canonical alias explanations.

The existing 15-minute capture and 30-minute grading jobs run this pipeline;
research never replaces pinned coefficients automatically. No new odds-quota
bypass, PrizePicks scrape, or external prediction service was added. Current
moneyline/spread/prop artifacts—including the disclosed XP manual override—are
retained. The alias fix may legitimately change a legacy interceptions baseline
by using its current canonical outcome history without counting duplicates.

Migrations 0011 and 0012 are additive and were exercised on isolated PostgreSQL
before production. Rollback should use the prior application image while retaining
the additive tables/column; do not drop availability or evidence history merely
to revert an application version.

Remaining work includes verified lineup/injury/weather/news feeds, trained
opportunity/opponent effects, safe settlement-aware joint models, closing-line
benchmarks, broader history coverage, source-specific withdrawal policies, and
prospective evidence. These changes do not establish a profitable betting edge.

When RSS feeds are configured, capture now stores up to five exact-name,
pre-capture headline references per player in the immutable feature snapshot.
The observation timestamp, not a publisher date, is the as-of boundary.
Headline evidence remains research-only: it does not establish an injury or
lineup fact and does not change serving probabilities.

For NFL longest-reception and longest-rush coverage, `scripts/ingest_history.py`
has an explicit `--with-play-props` offline option. It derives only maxima from
nflverse plays marked as completed passes or rush attempts with a named player;
the default historical ingest and all serving containers remain free of that
large play-by-play dependency. Missing player plays are not treated as zeroes.

Deployment verification (2026-09-06 UTC): 126 offline/isolated-PostgreSQL tests
passed, with one live test deselected. The lean production image imports the
research tasks without NumPy/SciPy; standard-library count CDFs matched SciPy
reference checks within 9.1e-13. A live capture archived 1,878 forecasts, including
1,642 feature/shadow records. Grading exposed 54 shadow reports and coverage
exposed 151 sport/stat families. All 20 returned NCAAF ranked props were marked
actionable and scheduled; dashboard HTTP health returned 200. Counts are a
point-in-time operational check, not evidence of predictive improvement.

## September 6 result-coverage follow-up

Verified ESPN NCAAF passing payloads can advertise a trailing `adjQBR` key
without providing that final value. The parser now accepts that specific
one-field omission while rejecting other length mismatches. No missing QBR or
player outcome is fabricated. Versioned `ncaaf_box3_` markers revisit the existing
seven-day completed-game window without erasing prior audits or replacing facts.
At verification, 35 successful runs inserted 1,394 additional stat rows (including
newly completed games). A repeat run selected zero games and inserted zero rows.

`/calibration/live` now includes bounded `unresolved_evidence` diagnostics,
deduplicated across model versions and exact market aliases. The report separates
missing team scores, games with no player facts, players with no facts, and
missing stat categories despite other player facts. Counts remain complete even
if the example list reaches its 200-item cap. No category implies a zero, DNP,
or bookmaker void; scoring and promotion gates remain unchanged.

The live check showed 89 unique unresolved outcomes: 60 had no recorded player
results and 29 lacked the requested stat despite other recorded player results.
Those corresponded to 359 missing grades across model versions. Verified
participation/category evidence or source corrections are still needed before
resolving them. The focused regression suite passed 63 tests (one live test
deselected), Ruff passed, and the dashboard returned HTTP 200.
