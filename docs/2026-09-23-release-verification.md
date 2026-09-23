# Release verification — September 23, 2026

This is the authoritative deployment status for the September 22–23 audit remediation. Earlier reports describe their observation times, not the current deployed state.

## Committed and deployed

- `abb81ca`: fantasy/scoring history, specialist defaults, sharp/soft prop comparisons, separate shadow ledger, lab artifact registry and promotion review, NFL weekly/EPA feed, retention reporting, tests and audit documents.
- `6c5b352`: fix the legacy `/nfl-predictor` redirect. Release verification found a cached static 307 without a usable destination; request-time rendering now redirects correctly to `/experimental`.
- API, worker, beat and evaluation rebuilt and replaced. Postgres and Redis were not replaced. No migration was needed.
- Production dashboard and localhost preview both run the final dashboard image. Old preview containers remain available for rollback; most recent is `fantasy-edge-grading-preview-before-20260923T120738`.
- Commits are local; no push was requested or performed in this release.

## Verified parity and checks

The repo and all four running Python services have the identical sorted-path/source-content SHA-256:

`56213fd3255a51897e217566a4369f499fa36d5426310cb31bc259a90b72372e`

Both dashboard containers match the final built image. All five application services were running with zero restarts and no OOM-killed status at verification.

- Backend suite: 669 passed, 1 intentional skip, 20 live tests deselected. Eleven focused tests passed after the final defensive guards.
- Final dashboard production build compiled successfully and passed lint/type checks.
- Deployed API HTTP 200: health, player-price comparison, NFL predictor, both leagues' decision-model routes.
- Local HTTP 200, without server-exception page content: `/fantasy`, `/fantasy/matchup`, `/fantasy/models`, `/best-bets`, `/experimental`.
- `/nfl-predictor` follows its redirect to `/experimental`, HTTP 200.
- Both Celery workers report all four new tasks registered. Beat now schedules research shadow capture and lab registration/review every 15 minutes, NFL stats refresh daily, and retention dry-run reporting daily.

## Evidence versus approval

The model registry contains the saved lab artifact and its first immutable prediction. Promotion review ran but did not pass; no serving model was promoted. The separate shadow ledger's initial 105 observations are never actionable and have no stake or exposure. Closing observations remain proxies unless official-close and settlement evidence qualify them.

NFL weekly stats refreshed successfully; 634 team-game EPA rows were archived. Two consecutive refreshes returned zero additional inserts, demonstrating idempotence. EPA features are available for research; newly fitted EPA coefficients are not claimed or deployed. Market blending is a separately frozen, unvalidated candidate.

The current prop-comparison smoke found 48 fresh player quotes but zero eligible sharp/soft comparisons. This is an inventory limitation, not a successful strategy-validation result. Team-market collection still conserves the remaining Odds API quota pending reset.

Specialist history/default support is deployed. Complete lineup probabilities can still be withheld for genuinely missing starters, rookie distributions or availability evidence. Latest checks identified an empty Sleeper starter slot and three ESPN rookie blockers, including Price's availability flag.

Raw retention is **dry-run only**. Its first 90-day manifest found zero eligible bytes and deleted nothing. No claim of disk reclamation or active deletion policy is made.
