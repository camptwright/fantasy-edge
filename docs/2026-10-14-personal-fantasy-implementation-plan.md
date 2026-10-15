# Personal fantasy implementation plan

## Order and ownership

1. Coverage agent: shared week-level projection states; missing/bye/absence handling; complete-horizon waiver/trade comparisons; bounded multiweek plans and practical gain thresholds.
2. Availability agent: common status vocabulary, dated same-team practice evidence, legal late-swap contingencies and accurate player labels.
3. Model/features agent: comparable frozen forecast evaluation, season/week/position reporting, dynasty package/pick scenarios and observed role trends.
4. Integration: one model/release manifest, cached background standings/trade discovery, tool-specific API responses and on-demand player detail; persistent personal decision journal; quieter unified player UI.
5. Verify: offline/dedicated-test-database regression, current release fingerprints, coordinated deployment and live multi-league workflows, payload and timing measurements.

## Acceptance

- Missing projections never become measured zero or full modeled lineup gains.
- Dated byes/absence and legal roster slots remain distinct from incomplete evidence.
- Future outcomes and draft-pick prices are not fabricated; supplied assumptions are explicit.
- GET requests do not launch trade search or playoff simulation.
- Tool responses omit unused catalogs and series; player details are loaded when requested.
- Personal decisions save frozen internal evidence only; no fantasy-platform transactions occur.
- Prospective qualification uses the current version, a cohort selected before results, and observed future outcomes; retrospective estimates are displayed separately.
- Producers and readers share verifiable release fingerprints and prediction input/version evidence.

No existing user changes will be overwritten. The starting repository is clean at f82b8d1.

## Implementation and verification

Completed and deployed the five repairs and six personal workflows:

- Shared `engine_coverage` states distinguish finite projections, validated byes, dated confirmed absences, and missing coverage. Waivers, trade outlook/discovery, and playoff strength withhold incomplete comparisons. Unresolved roster positions are not silently omitted. Incomplete completed-matchup scores update neither team's standings; incomplete history withholds playoff odds.
- Backend images seal source/dependency/runtime/packaged-model fingerprints. Production API, worker, evaluation, beat, preview API, and observer all match release `4cef0c2e2d68d9f360e0db47d28f138c19bd9cd46707d094f07f04781d091c51` across 339 checked source files. Both dashboard inventories and sealed artifacts match repository source, build `QnLFWp0dyD4IrVeHd1mVJ`. Changes are deployed but not yet committed/pushed.
- Tool-specific views retain only relevant sections; compact catalogs restore display defaults without inventing point values. Selected player detail is retrieved on demand and rejects a different checkpoint with HTTP 409. Trade discovery and standings simulations are produced during scheduled background refresh, not GET requests; summaries bind source time, expiry, revision, model version, recipe, and digest.
- Status normalization includes `INJURY_RESERVE`. Practice evidence requires matching season/week/team and bounded report/fetch freshness. “Scheduled” is not clearance; conflicting or unfamiliar restrictions show “Review”. Availability dates and withheld-evidence reasons remain visible.
- Frozen cohort selection no longer uses realized fantasy scoring to choose participants. Qualification exposes position/week results and season-week-clustered uncertainty. Reconstructed blends are explicitly retrospective and cannot qualify for promotion.
- Late-swap plans use legal, unlocked, same/later-kickoff bench replacements and show backup points. Held event evidence suppresses expected value without removing the contingency. Independent contingencies cannot share one replacement simultaneously.
- Waivers offer 2/3/4-week horizons, weekly gains, alternative drops, needed-by weeks and available kickoff timing. Engine, specialist-streaming, and legacy waiver calculations suppress gains below one point. IR/taxi players remain protected.
- Dynasty trade scenarios support contender/rebuild/balanced goals, player packages, rookie picks, supplied price provenance, and matching archived market-index changes, separate from lineup impact.
- Player profiles and comparison share observed role trends and navigation. Pending-correction games are withheld. Unknown usage measurements remain unknown.
- “My decisions” stores immutable lineup/pickup/trade expectations, ownership, scoring contract, exact game/kickoff references, model identity, and notes. Retry IDs are idempotent; conflicts reject. Only verified final league scores grade records. The journal writes through authenticated production API, not the read-only preview. No production test decisions were created.
- Primary decisions precede collapsed ranking/history/model-evidence sections.

Regression: **1,134 backend tests passed**, one skipped, 20 deselected; **64 dashboard tests passed**, TypeScript and lint passed; `git diff --check` clean. Durable journal behavior was tested against the dedicated disposable database, never production. Live smoke checks covered nine tools across three leagues (27 pages), with no server errors. Browser checks verified waivers, journal, dynasty controls, catalog/detail navigation, and observed role trends.

### Measured response improvement

Five warm HTTP reads per endpoint for Inaugural Crossover League, measured during verification. These are point-in-time samples, not a sustained-load p95 or browser latency benchmark.

| View | JSON bytes | Median ms | Largest of five ms |
| --- | ---: | ---: | ---: |
| Legacy overview | 1,060,419 | 127.7 | 202.4 |
| Tool overview | 70,611 | 150.4 | 153.6 |
| My team | 68,127 | 127.4 | 152.8 |
| Waivers, 2 weeks | 354,728 | 154.7 | 156.9 |
| Players catalog | 253,412 | 154.8 | 156.8 |
| Trade catalog | 247,557 | 129.1 | 158.0 |
| Waivers, 4 weeks | 335,384 | 259.0 | 263.0 |
| Cached standings | 2,808 | 137.0 | 164.4 |
| Cached trade discovery | 395 | 137.8 | 164.3 |
| Selected player detail | 3,413 | 155.5 | 170.4 |

Most serialization and evidence attachment still run through the legacy overview adapter before trimming. Payload savings are verified; further query/adapter specialization is an optional optimization, not a claim that all server-side overhead is eliminated.

## Honest remaining evidence limits

- The current v1 engine has **one graded week of six required**; depth has **zero of five**. Scheduled prospective collection/grading is functioning, but future results cannot be manufactured. Both remain unpromoted research; reconstructed blend results do not count as qualification.
- Missing player/week coverage still withholds offensive guidance or trade discovery. For example, the live waiver screen identifies Rico Dowdle's missing Week 6 coverage while retaining supported defense streams. Missing evidence is not an expendable-player verdict.
- K/DEF streaming uses weekly platform evidence; the offensive engine is not a qualified specialist ROS model. No default is presented as independent validation.
- Draft-pick ownership and future pick prices are not verified automatically. Unpriced picks prevent a complete package total; entered values are explicitly supplied market-index scenarios, not dollar or fantasy-point prices. Market trends require matching archived observations.
- Target/carry shares require verified team denominators; red-zone series require observed stats. Available snap/target/carry trends describe history, not proof that a projection change was caused by that role change.
- Claim timing shows a needed week/kickoff and platform waiver rules, not an invented guaranteed claim deadline. No FAAB bid optimizer or fantasy-platform transaction submission was added.
- The journal UI supports current starting lineups and one-player pickups/trades; its API can freeze trade packages. Outcomes describe observed player scores, not causal proof of a trade or pickup's benefit.
