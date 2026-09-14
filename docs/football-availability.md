# Injury evidence and football availability

General injury context distinguishes unsupported coverage, missing provider
identity, absent/invalid/empty/stale archives, no current player report, fresh
injury reports, and MLB roster status. A malformed row does not discard valid
rows. Neither absence from a report nor an active roster status confirms a start.

The NFL/NCAAF collector polls ESPN summaries for up to 160 scheduled, linked
games within seven days, every 30 minutes. It verifies event ID, kickoff, and
the report's team membership against event participants. Null kickoff games
are explicitly reported as unknown. Failed or absent sections stay visible;
no fallback to an older successful snapshot hides a failed fetch.

Each prop receives game-specific evidence. The event ID and kickoff must still
match, the observation must be no more than an hour old, and individual report
dates must be within seven days and not in the future. Within 24 hours of kickoff,
Out, Doubtful, and contradictory ESPN statuses trigger a recommendation review
hold. Questionable is a warning. Numeric projections and bookmaker settlement
rules are unchanged. Forecasts retain the exact injury context used for serving.

ESPN event pages contain team injury information, not an authoritative inactive
list. The app explicitly sets official_game_status_verified=false. No player
report means availability is unconfirmed. Missing NCAAF sections are labeled
not_provided, not healthy or fully covered.

## Remaining source work

Official NFL inactive/game-status reports and conference/team NCAAF availability
reports still need dedicated, verified adapters. ESPN coverage does not establish
those claims. Source references:

- https://www.nfl.com/inactives/
- https://www.nfl.com/injuries/
- https://www.secsports.com/fbreports

This is the first game-linked evidence layer, not complete college-football
availability coverage or an injury-adjusted numeric forecasting model.
