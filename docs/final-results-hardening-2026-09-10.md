# Final-result and model-input audit — September 10

Production audit at 15:18 UTC found 35 finals in the prior three days (33 MLB,
one NFL, one NCAAF). All had both team scores and at least one player-stat row.
This is game-level coverage, not proof that every participant/market is complete.
In the prior 12 hours NFL ingested 136 and MLB 1,346 result rows.
Correction telemetry showed 51 applied and 12 pending player-stat corrections.

Deployed correction quarantine excludes a player's entire game from new baseline
projections and shadow features while any stat has a pending correction. This
prevents aliases, composites and opportunity features using inconsistent subsets.
Applied/superseded proposals release the game; missing values are never zero-filled.
The helper is fingerprinted in model_version. Existing forecast archives are not
rewritten. This is an input-integrity change, not candidate parameter promotion.

41 regression tests passed, including quarantine/restoration and existing repair,
grading, versioning and performance tests. Test archives now use temporary paths.
Only API, worker and evaluation services were deployed; remote access untouched.
Post-deployment MLB live props returned 76 offers in 0.26 seconds.

Bounded retries checked four due MLB games without errors or changes; NFL had no
due games. Grading and candidate evaluation completed. The newly settled NFL
market blend had Brier 0.26273 versus 0.27041 baseline across 12 selected outcomes
from ONE game. Not sufficient for promotion. No candidate was promoted.

## Remaining work

- NBA/NHL collectors still use old successful-game markers rather than shared
  retry/correction cursors. Migrate without losing participation/identity checks.
- Team scores update, but incremental Elo/scoring averages use a first-final
  transition guard; retroactive score corrections need audited deterministic
  rating replay rather than double-applying a result.
- Game-level player-stat presence does not prove market-specific completeness.
- Extend unresolved-correction input policy consistently to other historical
  training/backtest builders, not only live projections and captured features.
- Continue prospective evaluation across independent games. Current market
  candidate evidence does not justify production recalibration.
