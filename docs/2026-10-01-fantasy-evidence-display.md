# Provider evidence display

Model evidence now presents provider capture count, unique league/player/game observations, unique graded observations, additional versioned captures and per-recipe capture counts outside the raw JSON details. It labels legacy v1 versus scoring-rule-bound v2 and explicitly identifies all-configured-league scope. Status counts remain capture counts, not independent observations. Missing reports display unavailable rather than fabricated zero counts.

No prediction logic or grading criteria changed. Focused observation-accounting and archive-grading tests passed. The host build was blocked writing .next/trace by filesystem permissions; verification uses the production container build instead.
