# Audit remediation: verified candidate versus deployed state

This report supersedes earlier status summaries for the work below; it does not rewrite their historical measurements.

## Release authorization

The user confirmed on September 23 that the other editor finished and authorized release. The verification below describes the pre-release measurements. See the release-verification report for the resulting commit and deployed fingerprints. Existing review/proposal documents were preserved.

All four candidate images build successfully. Candidate API requests were exercised in a one-off container against live read-only data, not by replacing the running API. Source fingerprints include sorted `src/**/*.py` paths and contents:

- Repo and candidate: `56213fd3255a51897e217566a4369f499fa36d5426310cb31bc259a90b72372e`
- Running API: `48b25bac49ccc1bbb1001627acbc733fee587824a0668a7f21c299743796a6a3`
- Pre-release Git HEAD was `9d5ee8e`.

The differences are now explicit, not represented as a completed deployment. After editor confirmation, inspect the final diff, commit the agreed files, build from that commit, replace API/worker/beat/evaluation/dashboard as applicable, verify the local preview, compare fingerprints again, and update this report with the resulting commit and running hashes.

## Results by priority

1. **Reconciliation and release:** final regression run: 669 passed, 1 intentional skip, 20 live tests deselected. Eleven focused tests passed after the final two defensive guards. Release awaits editor confirmation.
2. **Sharp/soft prop pricing:** candidate `/markets/price-comparisons` supports `kind=player|team|both`. It compares exact player/game/stat/line contracts, separates bookmaker brands from providers, rejects integer-line push ambiguity, and requires two-sided sharp prices plus contemporary target quotes. Candidate smoke returned HTTP 200 with 48 fresh player quotes and zero qualifying matches. This is not a claim of newly available profitable bets. Team-market decision: conserve quota and wait for the Odds API reset; no plan upgrade or quota bypass.
3. **Lab artifact and promotion:** the existing lab artifact was saved under the models volume and registered as version `9544141108ba96216ffa334e51028f601c0e24cb89925ff9ab6a67addcbd7375`. Production database now contains one artifact and one prediction. A repeated job added no duplicate forecast. The paired prospective review ran and withheld promotion: no completed prospective games, evaluation window open, and insufficient comparable performance evidence. Historical aggregate metrics were not substituted for version-specific prospective results.
4. **Separate shadow ledger:** one-off jobs captured 105 immutable research observations under `research-shadow-ledger`, outside `ledger_bets`. Repeated execution captured zero duplicates. Every entry is non-actionable, has no stake, and is excluded from exposure. Future exact-contract closing observations remain proxies until settlement/official-close evidence exists. No close had yet been captured in the smoke run. Scheduled capture is wired in candidate code, not active in the old running beat.
5. **Kickers/defenses:** prefer reconciled historical distributions already collected. Where absent, candidate code uses explicitly labeled normal-position assumptions: K SD 5 fantasy points, DEF SD 7, centered on the fresh provider projection. These are chosen defaults, not fitted/calibrated variances; no synthetic games are added to history. ESPN's remaining candidate blockers are Price, Concepcion, and Tate; Price also needs availability review. The latest Sleeper matchup contains an empty starter sentinel `0`, so it is withheld for an incomplete lineup, not K/DST history. No roster changes were made.
6. **Raw archive policy:** a bounded 90-day dry-run policy targets only redundant `result-observations` JSON. It preserves latest sync evidence, all correction hashes, unresolved games, and observations without durable final stats. Forecasts, receipts, artifacts, weather, settlement evidence, and shadow records are outside scope. The first manifest found zero eligible bytes and deleted nothing. Automatic deletion is **not implemented/enabled**; this is a policy/manifest stage, not a claim that disk usage was reduced.
7. **NFL stats, EPA, and market blend:** the deployed worker lacked `nflreadpy` and had no scheduled call to the old importer. A dependency-light official-CSV path refreshed 2026 player stats and archived 634 team-game EPA rows across 2025/2026. Two consecutive executions succeeded and reported zero additional inserts after the initial refresh. They did not overwrite existing stats; the established correction workflow remains responsible for corrections. EPA features are timestamped, deduplicated prior-game aggregates, with missing/stale states explicit. They are not yet fitted into new coefficients. A 75% lab / 25% fresh sharp-market research candidate is exposed and frozen separately; its review compares it with the unblended lab and market benchmark. It is not the serving model. The first immutable lab forecast predates the EPA archive and was not retroactively enriched.

## Verification and remaining work

Candidate HTTP checks passed for prop price comparisons, NFL predictor, and both leagues' decision-model endpoints. The NFL predictor returned 56 upcoming fixtures with explicit missing-coverage states where relevant. No validation flags were overridden.

Remaining implementation/evidence work: release after editor confirmation; execution policy for approved raw-file deletion; independent training/holdout testing of EPA coefficients; prospective outcomes for lab/blend/lineup probabilities; ESPN rookie/availability coverage; fresh sharp/soft quote overlap. Future outcomes and absent quotes cannot be created by changing a gate.

Official source documentation: [nflverse player/team stat loaders](https://nflreadpy.nflverse.com/api/load_functions/). CSV schemas were additionally inspected directly from the official nflverse releases before implementation.
