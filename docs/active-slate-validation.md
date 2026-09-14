# Active-slate validation

`python -m scripts.validate_active_slate` performs bounded read-only concurrent
checks of the live NFL/NCAAF/MLB signals and props and the three dashboard pages.
It never polls a provider, spends Odds API credits, edits quotes, or refreshes
availability timestamps. There are at most three concurrent requests and ten
rounds. Responses larger than 4 MiB and p95 above five seconds fail validation.

Celery runs three rounds every 30 minutes against the Compose API and dashboard.
Results are archived under `active-slate-validation`; the current report is at
`/calibration/active-slate`. Reports older than one hour are explicitly stale.
For the separate Mac preview, the CLI defaults to its actual container address.
An empty live feed is **awaiting_live_quotes**, never a successful active-slate test.

## September 9, 2026 — 18:39 UTC

45 requests, concurrency three, no HTTP errors or partial-page warnings:

| Route | Actionable offers | Measured p95 |
| --- | ---: | ---: |
| NFL signals | 256 | 0.050s |
| NCAAF signals | 190 | 0.060s |
| MLB signals | 84 | 0.062s |
| Best Bets | — | 0.301s |
| Recommendations | — | 0.349s |
| Calibration | — | 0.846s |

All three live player-prop feeds were empty. Underdog's documented public endpoint
returned HTTP 426. Its stale quotes remain excluded. PrizePicks is prohibited by
repository policy. Other paid sports are paused under the retained NFL budget policy.
NFL's next two-hour paid refresh window opens September 9 at 22:20 UTC / 5:20 p.m.
Central, for the 00:20 UTC kickoff. Last reported balance is 40 credits, floor 10;
no budget override was made. Scheduled validation can verify non-empty NFL offers
after guarded ingestion supplies them, but cannot guarantee that the provider does.

The disposable database suite validates 30 populated players per sport across
projection batches and pages, checking identical probabilities and edges against
the legacy path. This is synthetic functional coverage, not real live quote coverage
or proof of production performance under a large populated player-prop slate.
