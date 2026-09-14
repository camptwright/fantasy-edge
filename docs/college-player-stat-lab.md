# Power Four player stat lab — September 12, 2026

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
