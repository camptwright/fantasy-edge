# Rule-bound historical provider grading

New provider forecasts with an available official scoring-contract hash use a separate v2 identity containing that hash. Legacy v1 identity construction is preserved. Immutable old captures are not amended or treated as rule-bound.

ESPN provider grading now attempts the reconciled historical-player archive only when matchup results are missing or the player is absent. It never overrides conflicting/invalid matchup values. The adapter requires exact league, game, season, week and frozen scoring-contract bindings; final game status; a pregame capture; the 24-hour result delay; ten overlapping reconciled players with no conflicts; and a finite actual. Missing evidence remains withheld.

27 focused tests passed. Backend services were rebuilt and deployed after idle-worker verification. No prediction weights, probability calibration or promotion gates were changed. Legacy captures lacking official rules cannot recover through this fallback. Versioned forecasts must not be pooled as independent trials merely because multiple recipes captured the same event.
