# Provider coverage and quota dashboard

`/providers` reads existing Odds API and aggregate-provider telemetry plus `/calibration/provider-coverage`. Page views never call upstream providers, reserve credits, or change pacing. Provider balances are last-observed, not live. Local UTC daily reservations are not provider balances. Guard expiry is a retry opportunity, not a quota reset.

Coverage scans at most 20,000 recent player-prop observations from seven days, deduplicated by source/event/player/stat/line. It reports sample truncation, markets, last observation/confirmation, and mutually exclusive quote-eligibility blockers. Historic provider names can appear even when their collectors are disabled. The counts are not full-provider inventories, distinct players, model qualifications, positive-EV bets, or legal availability claims. Team odds are outside this first coverage panel.

Verified five focused tests, production build, HTTP 200, and a 0.39-second live API scan of 18,270 observations without truncation. SGO NFL/MLB sample offers passed freshness/pregame checks; many other observations belonged to already-started events. Legacy Underdog rows also had stale/withdrawn/unlinked exclusions. No ingestion or betting-model settings changed.

Next: add price/history/model/EV stages using serving-identical rules, team-market coverage, and source rejection telemetry before canonical quote insertion. Do not infer upstream identity failures solely from stored quote rows.
