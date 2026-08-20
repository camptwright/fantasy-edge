# NFL data-source decision

## SportsBlaze

SportsBlaze is a viable optional **validation** source, not a replacement for
the betting-line feed. Its documented NFL core endpoints provide daily
schedules, rosters, standings, and boxscores; they require a SportsBlaze API
key. The free plan is limited to 10 requests/minute and can be delayed by up
to three minutes.

That means it could be useful later for:

- independent final-score and player-boxscore checks;
- roster/injury identity cross-checks before an nflverse projection run;
- detecting disagreements between ESPN and the model's game metadata.

It does **not** currently solve the team's missing-market problem: the public
documentation does not expose sportsbook spreads, totals, moneylines, or
player prop lines in the core NFL endpoints. We therefore do not add a
credential or poller yet. The current source order remains:

1. ESPN for schedule and published game markets;
2. permitted odds providers for bookmaker lines;
3. nflreadpy for historical modeling;
4. SportsBlaze only after an API key is intentionally provisioned and a
   validation adapter is tested against stored ESPN/nflverse results.

Revisit this decision if SportsBlaze access is purchased or its account
documentation confirms a market/odds endpoint.
