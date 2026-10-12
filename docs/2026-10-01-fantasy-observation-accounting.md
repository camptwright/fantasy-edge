# Distinct provider observations

Provider report now separates capture count, unique league/player/game combinations, additional versioned captures, unique graded combinations and capture counts per recipe. These are descriptive counts, not independent sample sizes: games and cross-league players remain correlated. No archive records are removed, no metrics are pooled and no promotion is authorized.

Pre-deploy live check found 1,039 captures representing 989 unique league/player/game combinations. Fourteen focused tests passed (pytest cache writing was sandbox-restricted, but tests completed). Backend images rebuilt and deployed after idle-worker verification.

The preceding strict-grade repair is live: new rule-bound ESPN records require the historical archive even for rostered players, and archive source/schema and recomputed scoring-contract hash are checked. Legacy captures remain separate. Future work remains on missing historical evidence, explicit user-facing cohort comparison and probability calibration.
