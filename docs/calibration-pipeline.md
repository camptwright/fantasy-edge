# Calibration pipeline

`python -m scripts.evaluate_all` performs a read-only evaluation for every
configured sport and emits JSON. Team replay now uses the latest quote at or
before kickoff and excludes fixtures without known times. Player replay uses
linked pregame quotes, exact normalized stat outcomes and prior-day history.
One player/game/stat sample is counted across books. Pushes are excluded from
binary scores. Unknown settlement rules, DNP/void handling, event-time publication
history and correlated samples still require additional validation.

Celery runs `fantasy.evaluate_models` every 24 hours with a Redis lock and hard
runtime limit. Reports, including bounded sigmoid candidate parameters and held-out
scores, are versioned by timestamp/UUID under the raw volume's `calibration/`.
Reports do not automatically alter production probabilities. Candidate selection
uses the early 70% of samples; the late 30% is diagnostic held-out evaluation.
This is not a complete multi-fold promotion gate.

New Underdog game props can resolve through an exact sport, home name, away name
and kickoff match. Series/season appearances are not assigned to a game.
Unresolved quotes remain unchanged; old append-only quotes are not guessed or
rewritten. Deduplication now scopes to game ID so a new game's identical line
is recorded. This does not yet distinguish separate unresolved provider events.

`fantasy.archive_news` stores hourly RSS/Atom snapshots under `news/`, preserving
the source publication string and UTC observation timestamp. The earliest
archived observation establishes when the app first had that headline. Only the
configured reader's bounded headline set is archived; this is not full news
coverage. Headlines currently provide narrative context, not numeric model inputs.

Next requirements: complete provider event identity and settlement rules, add
missing sport/player outcomes, fit sport-specific distributions and opportunity
features, capture immutable forecasts, add independent promotion/rollback gates,
and evaluate injury/lineup/news features against baseline and market references.
Historical timestamps are trusted as stored; availability audits remain necessary.

## Sport distributions and MLB results

The daily report now includes `sport_distributions` for each sport. Separate
online linear regressions learn score-margin and total bias/scale/residual
variance from that sport's own completed games. Inputs remain the existing
Elo margin and scoring averages. Predictions require at least 100 training
observations, and all updates are delayed until the next UTC day. Reports
compare candidate and baseline probabilities on identical market samples;
point RMSE alone is not evidence of probability calibration. Candidates stay
in evaluation and do not replace serving probabilities.

The hourly `fantasy.sync_mlb_results` job imports at most 20 unprocessed official
MLB boxscores, newest first. It uses stable MLB player IDs and explicit game
participation, preserves separate batter/pitcher statistics, and derives singles
and hits+runs+RBIs only when every component exists. Repeated runs are idempotent.
Per-game ingestion audit records make backfill restartable. Existing outcomes
are preserved; official corrections, unmapped player retries and bookmaker
void/DNP rules are not yet implemented. No new schema is required.

First deployed batch: 20 games, 5,962 outcome rows. First comparison: NFL spread
Brier 0.26594 baseline versus 0.25543 candidate (179 samples); NFL totals
0.27177 baseline versus 0.27329 candidate (137 samples). No promotion occurred.
Other sports have point-error measurements but currently lack historical
spread/total quote samples. Further result feeds and promotion gates remain work.

## NHL results and candidate review

The hourly `fantasy.sync_nhl_results` job imports up to 20 unprocessed completed
NHL games. Player identities are sourced from official NHL player profiles by
stable ID, not boxscore initials. Only players with positive recorded ice time
produce outcomes; unused goalies are excluded. A Redis lock prevents overlapping
identity imports. Per-game audit rows and unique player/game/stat rows make
restarts safe. Historical results are first-observed snapshots; correction and
bookmaker settlement handling remain separate work.

Sport distribution reports now contain a `promotion_review`. Candidate/baseline
events and outcomes must match exactly. Review requires at least 200 independent
games, lower Brier and log loss, a game-cluster bootstrap interval showing Brier
improvement, comparable market benchmarks and prospective validation. Missing
evidence is an explicit blocker. Current evaluation does not provide prospective
validation or market benchmarks, so this does not enable automatic deployment.
The interval does not model cross-day temporal dependence or fix data provenance.

## NBA history and prospective baseline snapshots

`fantasy.sync_nba_results` runs hourly, backfilling at most 20 completed ESPN NBA
boxscores using the same event IDs as NBA schedule ingestion. It creates player
identities from stable IDs and full display names. Explicit DNPs are excluded;
zero rounded minutes do not erase a confirmed appearance. Stat columns are mapped
by label and combination stats require all components. Completed-game markers and
unique outcome keys make retries idempotent. Like other adapters, correction and
bookmaker-specific void handling remain outstanding.

`fantasy.capture_forecasts` runs every 15 minutes. It snapshots current API signal
and prop calculations using a repeatable-read database transaction. Only linked,
qualified player props and scheduled games with known future start times at the
end of capture are included. Each record contains the immutable quote ID, game ID,
line, prediction and numerical model inputs. The archive includes a SHA-256 digest
of the serving probability code and an actual capture timestamp. These are sampled
baseline forecasts, not a record of every page view or candidate forecasts.

Files are published atomically to the persistent raw volume's `forecasts/` folder.
Unlinked props and games that start during capture are excluded and counted. News
does not influence these numeric forecasts yet. Settlement/grading of these
snapshots, prospective candidate comparison, retention and dashboard visibility
are still required before this becomes an automatic promotion loop.
# Live grading and exposure

`fantasy.grade_forecasts` runs every 30 minutes, reads immutable pregame captures,
and publishes an atomic, versioned `raw/grading` report.
`GET /calibration/live` and the Calibration dashboard expose counts and per-sport,
market, player/team and model-version Brier/log-loss scores. Reports older than
two hours are flagged stale. No serving model is promoted or changed.

The cohort selects the earliest capture per model/event/market/player, breaking
same-time ties by quote ID. Repeated snapshots, books, lines and complementary
sides do not become extra samples. Player probabilities are graded on OVER.
Independent game counts accompany sample counts because props are correlated.
Pushes, incomplete finals, missing player results (including potential DNP),
cancelled events, unsupported markets and invalid timing do not enter metrics.
These are statistical outcomes, not bookmaker-specific settlements or profit.
All facts are reread each run to incorporate delayed results/corrections; this
does not manufacture results that the ingestion pipeline has not supplied.
Archive corruption fails the job closed, leaving the prior report to go stale.
The initial implementation streams archive files but retains the selected cohort
in memory and rescans history; a durable incremental index is future scaling work.
