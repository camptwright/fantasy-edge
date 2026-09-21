# Power Four player stat lab — September 12, 2026

## September 14 automation update

College prospective testing is now deployed as `fantasy.college_lab_prospective` every 15 minutes. Each run refreshes projections from current eligible results; exact-ID roster/conference snapshots are reused for up to six hours. Source refresh failures prevent new captures but do not prevent grading existing forecasts. Read-only worker transactions use fresh database sessions.

The first eligible prediction per model/player/game/stat is captured between 72 hours and five minutes before known kickoff. Game status and kickoff are rechecked before atomic, create-only publication. Original predictions are never rewritten. Current corrected final facts are graded on subsequent runs; pending corrections and missing results stay ungraded. Code-versioned MAE is separate from the retrospective scorecard, with no automatic promotion. The shared result queue now includes these college archives.

Verified 14 focused tests, production build, two manual runs, and repeated scheduled runs through 2026-09-14 12:14 UTC. At that check, zero eligible captures was expected: the earliest player game was September 17 at 23:30 UTC, opening its capture window September 14 at 23:30 UTC (6:30 p.m. Central). This verifies scheduling and eligibility behavior, not completed prospective forecast accuracy. The first real captures and final-result grades remain to be observed.

The following describes the initial manual-only release and is retained as historical context.

Available on Experimental below the NFL roster lab. Manual refresh: `python -m scripts.evaluate_college_player_lab` inside the API environment. This version is an archived retrospective evaluation and current historical-estimate explorer, not automatic college pregame capture. NFL prospective recording remains separate and unchanged.

## Scope and evidence

Current ESPN standings and team rosters establish exact conference/team/athlete IDs: 17 ACC, 18 Big Ten, 16 Big 12 and 16 SEC teams. Notre Dame is independent and excluded. Membership follows football, not other sports. Sources: [ESPN standings](https://site.api.espn.com/apis/v2/sports/football/college-football/standings?season=2026), [ACC 2026 opponents](https://theacc.com/news/2025/12/16/football-acc-announces-2026-league-opponents-as-move-to-nine-game-conference-schedule-begins.aspx), [Big 12 2026 schedule](https://big12sports.com/news/2026/1/21/big-12-conference-announces-2026-football-schedule.aspx). Provider membership is checked against expected counts and conflicts fail closed. Source ID/roster snapshots are retained alongside reports.

The player table currently lacks NCAAF current-team links. The lab resolves current roster membership through `espn_ncaaf` athlete IDs without modifying production identities or name matching. Prior games not involving the player's current school are excluded; current roster selection and corrected history mean these tests are not point-in-time historical reconstructions.

## First run

- 67 mapped schools; 742 players with current-season observations across 66 schools.
- 60 completed Power Four games have cohort stat rows (presence, not proof of complete boxscores).
- Provider week labels: 58 week-1 games, two week-2 games. Do not describe this as two complete weeks.
- 500 eligible player-stat retrospective tests; 1,587 observed player-stat outcomes excluded for fewer than eight prior observations.
- 190 players have at least one current estimate; Texas has 15 player cards.

Recipe: existing NFL lab's last-20 baseline and conservative opportunity blend, no retuning against these outcomes. Training precedes each target's calendar day. Zero is accepted only when explicitly stored; missing fields stay missing. Pending player-game corrections are excluded. Metrics are separated by conference/stat with sample and independent-game counts. No pooled cross-unit score or promotion gate is implied.

Passing-yard candidate MAE was lower in ACC, Big Ten and SEC, higher in Big 12. Rushing-yard MAE was higher in ACC, Big Ten and Big 12, lower in SEC. Receiving candidates equal baseline because target history is absent. Samples are small and correlated within games; these differences do not establish superiority.

## Remaining work

Automate refresh and prospective college forecast capture; preserve frozen pregame records and grade corrected finals. Add verified game-day availability, transfer/role-aware history, and independent boxscore-completeness checks before stronger readiness claims. Never lower history requirements simply to increase displayed coverage. Current player estimates are conditional on playing and do not change Best Bets or production calibration.
